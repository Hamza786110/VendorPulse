from datetime import datetime
import os
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from bson import ObjectId

from contracts.models import ContractDocument, ContractStatus, ExtractedContractFields
from contracts.utils import save_upload, extract_text_from_file
from contracts.chains import extract_contract_fields
from contracts.notifications import notify_extraction_issue, notify_contract_updated, diff_extracted_fields

from retrieval.loaders import load_document
from retrieval.chunking import chunk_documents
from retrieval.vectorstore import store_chunks, query_contract,delete_contract_chunks
from auth.dependencies import get_current_user, get_db  # auth + db dependencies

router = APIRouter(prefix="/contracts", tags=["contracts"])


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


@router.post("/{contract_id}/extract")
async def extract_contract(
    contract_id: str,
    background_tasks: BackgroundTasks ,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    contract = await db.contracts.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

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
    contract = await db.contracts.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

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
    contract = await db.contracts.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    if contract.get("uploaded_by") != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Not authorized to search this contract")

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

@router.post("/{contract_id}/replace")
async def replace_contract(
    contract_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    contract = await db.contracts.find_one({"_id": ObjectId(contract_id)})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.get("uploaded_by") != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Not authorized to update this contract")
 
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
