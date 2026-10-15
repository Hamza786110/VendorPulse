from datetime import datetime
import os
import re
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks #type: ignore
from bson import ObjectId#type: ignore
from bson.errors import InvalidId#type: ignore

from contracts.models import ContractDocument, ContractStatus, ExtractedContractFields
from contracts.utils import save_upload, extract_text_from_file
from contracts.chains import extract_contract_fields
from contracts.notifications import notify_extraction_issue, notify_contract_updated, diff_extracted_fields

from retrieval.loaders import load_document
from retrieval.chunking import chunk_documents
from retrieval.vectorstore import store_chunks, query_contract,delete_contract_chunks
from auth.dependencies import get_current_user, get_db  # auth + db dependencies

router = APIRouter(prefix="/contracts", tags=["contracts"])


async def _get_owned_contract(db, contract_id: str, current_user) -> dict:
    """Valid ObjectId + belongs to the logged-in user, else a clean 400/404."""
    try:
        oid = ObjectId(contract_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid contract id")
    contract = await db.contracts.find_one({"_id": oid})
    if not contract or contract.get("uploaded_by") != str(current_user["_id"]):
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


def _ingest_to_vectorstore(file_path: str, contract_id: str) -> None:
    """
    Runs after the upload response has already been sent.
    """
    try:
        docs = load_document(file_path)
        chunks = chunk_documents(docs)
        store_chunks(chunks, contract_id)
    except Exception as e:
        print(f"[vectorstore] failed to ingest contract {contract_id}: {e}")


async def _find_existing_duplicate(db, user_id: str, this_oid, vendor_name: str | None):
    """Same user + same vendor name (case-insensitive) = same contract."""
    vendor = (vendor_name or "").strip()
    if not vendor:
        return None
    return await db.contracts.find_one(
        {
            "uploaded_by": user_id,
            "_id": {"$ne": this_oid},
            "extracted.vendor_name": {"$regex": f"^{re.escape(vendor)}$", "$options": "i"},
        },
        sort=[("_id", 1)],  # oldest one is the "original"
    )


@router.post("/upload")
async def upload_contract(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    try:
        # save_upload's returned id is just a filename-collision-avoidance
        # rest of the API (and the vectorstore) key on.
        _file_uuid, file_path = await save_upload(file)
        raw_text = extract_text_from_file(file_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    doc = ContractDocument(
        filename=file.filename,
        file_path=file_path,
        uploaded_by=str(current_user["_id"]),
        status=ContractStatus.UPLOADED,
        raw_text=raw_text,
    )

    result = await db.contracts.insert_one(doc.model_dump(exclude={"id"}, by_alias=True))
    contract_id = str(result.inserted_id)

    background_tasks.add_task(_ingest_to_vectorstore, file_path, contract_id)

    return {
        "contract_id": contract_id,
        "filename": file.filename,
        "status": ContractStatus.UPLOADED,
    }


@router.get("")
async def list_contracts(
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    cursor = db.contracts.find({"uploaded_by": str(current_user["_id"])})
    contracts = await cursor.to_list(length=100)
    for c in contracts:
        c["_id"] = str(c["_id"])
    return contracts


@router.get("/stats")
async def contract_stats(
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):

    # Dashboard numbers: how many contracts the user has uploaded, broken
    # down by processing status, plus how many are currently flagged. so it's cheap and exact.

    return await get_contract_stats(db, str(current_user["_id"]))


@router.post("/{contract_id}/extract")
async def extract_contract(
    contract_id: str,
    background_tasks: BackgroundTasks ,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    contract = await _get_owned_contract(db, contract_id, current_user)

    if not contract.get("raw_text"):
        raise HTTPException(status_code=400, detail="Contract has no extracted text to analyze")

    await db.contracts.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": {"status": ContractStatus.EXTRACTING}},
    )

    try:
        extracted: ExtractedContractFields = extract_contract_fields(contract["raw_text"])
    except Exception as e:
        await db.contracts.update_one(
            {"_id": ObjectId(contract_id)},
            {"$set": {"status": ContractStatus.EXTRACTION_FAILED, "extraction_error": str(e)}},
        )
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")


    # ---- Duplicate check: same vendor already uploaded by this user? ----
    # If so, don't keep two records. Fold this upload into the OLD record
    # (keeping the old version in previous_versions), email what changed,
    # and delete the new one.
    new_fields = extracted.model_dump(mode="json")
    original = await _find_existing_duplicate(
        db, str(current_user["_id"]), ObjectId(contract_id), extracted.vendor_name
    )
    if original:
        original_id = str(original["_id"])
        diff_lines = diff_extracted_fields(original.get("extracted"), new_fields)

        previous_versions = original.get("previous_versions", [])
        previous_versions.append(
            {
                "filename": original.get("filename"),
                "file_path": original.get("file_path"),
                "extracted": original.get("extracted"),
                "replaced_at": datetime.utcnow().isoformat(),
            }
        )
        await db.contracts.update_one(
            {"_id": original["_id"]},
            {
                "$set": {
                    "filename": contract["filename"],
                    "file_path": contract["file_path"],
                    "raw_text": contract["raw_text"],
                    "status": ContractStatus.EXTRACTED,
                    "extracted": new_fields,
                    "extracted_at": datetime.utcnow().isoformat(),
                    "extraction_error": None,
                    # old flag state described the old content; let the DAG re-evaluate
                    "flagged": False,
                    "flag_reason": None,
                    "flagged_at": None,
                    "alert_sent": False,
                    "previous_versions": previous_versions,
                }
            },
        )
        await db.contracts.delete_one({"_id": ObjectId(contract_id)})

        # Vector index: drop the old content + the duplicate's chunks, re-index under the original id
        for cid in (original_id, contract_id):
            try:
                delete_contract_chunks(cid)
            except Exception as e:
                print(f"[vectorstore] failed to clear chunks for {cid}: {e}")
        background_tasks.add_task(_ingest_to_vectorstore, contract["file_path"], original_id)

        old_path = original.get("file_path")
        if old_path and old_path != contract["file_path"]:
            try:
                os.remove(old_path)
            except OSError:
                pass

        background_tasks.add_task(
            notify_contract_updated, current_user["email"], contract["filename"], diff_lines
        )
        return {
            "contract_id": original_id,
            "merged_into_existing": True,
            "message": "This vendor already had a contract, so it was updated instead of duplicated.",
            "changes": diff_lines,
            "status": ContractStatus.EXTRACTED,
            "extracted": extracted,
        }

    await db.contracts.update_one(
        {"_id": ObjectId(contract_id)},
        {
            "$set": {
                "status": ContractStatus.EXTRACTED,
                "extracted": new_fields,
                "extracted_at": datetime.utcnow().isoformat(),
            }
        },
    )
    if extracted.confidence_notes:
        background_tasks.add_task(
            notify_extraction_issue,
            current_user["email"],
            contract["filename"],
            extracted.confidence_notes,
            False,
        )
    return {"contract_id": contract_id, "status": ContractStatus.EXTRACTED, "extracted": extracted}


@router.get("/{contract_id}")
async def get_contract(
    contract_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    contract = await _get_owned_contract(db, contract_id, current_user)

    contract["_id"] = str(contract["_id"])
    return contract


@router.get("/{contract_id}/ask")
async def ask_contract(
    contract_id: str,
    question: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Semantic search over one contract's stored chunks. Returns the top
    matching passages for `question`, not a generated answer — this is a
    retrieval endpoint, not a chat endpoint.
    """
    await _get_owned_contract(db, contract_id, current_user)

    results = query_contract(contract_id, question)

    documents = results.get("documents", [[]])[0]
    distances = results.get("distances", [[]])[0]
    matches = [{"text": text, "distance": distance} for text, distance in zip(documents, distances)]

    if not matches:
        raise HTTPException(
            status_code=404,
            detail="No indexed chunks found for this contract yet — it may still be processing.",
        )

    return {"contract_id": contract_id, "question": question, "matches": matches}




@router.post("/{contract_id}/replace")
async def replace_contract(
    contract_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    contract = await _get_owned_contract(db, contract_id, current_user)
 
    old_file_path = contract.get("file_path")
    old_extracted = contract.get("extracted")
 
    try:
        _file_uuid, new_file_path = await save_upload(file)
        raw_text = extract_text_from_file(new_file_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
 
    previous_versions = contract.get("previous_versions", [])
    previous_versions.append(
        {
            "filename": contract.get("filename"),
            "file_path": old_file_path,
            "extracted": old_extracted,
            "replaced_at": datetime.utcnow().isoformat(),
        }
    )
 
    # Reset flagged/alert_sent: the old flag state was about the old
    # content. The next DAG run should re-evaluate the new content fresh,
    # not stay silent because the old version already triggered an alert.
    await db.contracts.update_one(
        {"_id": ObjectId(contract_id)},
        {
            "$set": {
                "filename": file.filename,
                "file_path": new_file_path,
                "raw_text": raw_text,
                "status": ContractStatus.EXTRACTING,
                "extracted": None,
                "extraction_error": None,
                "flagged": False,
                "flag_reason": None,
                "flagged_at": None,
                "alert_sent": False,
                "previous_versions": previous_versions,
            }
        },
    )
 
    # Old vectorstore chunks belong to the old file's content
    try:
        delete_contract_chunks(contract_id)
    except Exception as e:
        print(f"[vectorstore] failed to clear old chunks for {contract_id}: {e}")
    background_tasks.add_task(_ingest_to_vectorstore, new_file_path, contract_id)
 
    try:
        extracted: ExtractedContractFields = extract_contract_fields(raw_text)
    except Exception as e:
        await db.contracts.update_one(
            {"_id": ObjectId(contract_id)},
            {"$set": {"status": ContractStatus.EXTRACTION_FAILED, "extraction_error": str(e)}},
        )
        background_tasks.add_task(
            notify_extraction_issue, current_user["email"], file.filename, str(e), True
        )
        raise HTTPException(status_code=500, detail=f"Extraction failed on the updated file: {e}")
 
    await db.contracts.update_one(
        {"_id": ObjectId(contract_id)},
        {
            "$set": {
                "status": ContractStatus.EXTRACTED,
                "extracted": extracted.model_dump(mode="json"),
                "extracted_at": datetime.utcnow().isoformat(),
            }
        },
    )
 
    diff_lines = diff_extracted_fields(old_extracted, extracted.model_dump(mode="json"))
    background_tasks.add_task(
        notify_contract_updated, current_user["email"], file.filename, diff_lines
    )
    if extracted.confidence_notes:
        background_tasks.add_task(
            notify_extraction_issue,
            current_user["email"],
            file.filename,
            extracted.confidence_notes,
            False,
        )
 
    # Best-effort cleanup of the old file on disk. Not fatal if it fails —
    # the record itself is already fully switched over to the new file.
    if old_file_path and old_file_path != new_file_path:
        try:
            os.remove(old_file_path)
        except OSError:
            pass
 
    return {
        "contract_id": contract_id,
        "status": ContractStatus.EXTRACTED,
        "extracted": extracted,
        "changes": diff_lines,
    }