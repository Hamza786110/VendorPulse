"""
contracts/routes.py

Endpoints:
  POST /contracts/upload          -> upload a contract file, extract raw text, save to Mongo
  POST /contracts/{id}/extract    -> run the Groq/LangChain extraction chain on a stored contract
  GET  /contracts/{id}            -> fetch a contract (incl. extracted fields once ready)

Adjust the `get_current_user` import below to match wherever Day 3's
auth dependency actually lives (likely `auth.dependencies`).
"""

from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from bson import ObjectId

from contracts.models import ContractDocument, ContractStatus, ExtractedContractFields
from contracts.utils import save_upload, extract_text_from_file
from contracts.chains import extract_contract_fields

from auth.dependencies import get_current_user, get_db  # auth + db dependencies

router = APIRouter(prefix="/contracts", tags=["contracts"])


@router.post("/upload")
async def upload_contract(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    try:
        contract_id, file_path = await save_upload(file)
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

    return {
        "contract_id": str(result.inserted_id),
        "filename": file.filename,
        "status": ContractStatus.UPLOADED,
    }


@router.post("/{contract_id}/extract")
async def extract_contract(
    contract_id: str,
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