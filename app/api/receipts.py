import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.models.receipt_evidence import REVIEW_NEW, ReceiptEvidence
from app.schemas.receipt import CreateReceiptRequest, ReceiptAccepted, ReceiptEvidenceView
from app.services.blob_url import BlobUrlError, access_url, storage_url

router = APIRouter(prefix="/receipts", tags=["receipts"])


def get_db(request: Request):
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


@router.post("", status_code=202, response_model=ReceiptAccepted)
def create_receipt(
    body: CreateReceiptRequest,
    background: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        stored = storage_url(body.image_blob_url)
        readable = access_url(body.image_blob_url, request.app.state.settings.blob_sas_token)
    except BlobUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row = ReceiptEvidence(
        jira_ticket_id=body.jira_ticket_id,
        evidence_file_url=stored,
        review_status=REVIEW_NEW,
        evidence_ready=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    background.add_task(request.app.state.processor.run, row.id, readable)
    return row


@router.get("/{evidence_id}", response_model=ReceiptEvidenceView)
def get_receipt(evidence_id: uuid.UUID, db: Session = Depends(get_db)):
    row = db.get(ReceiptEvidence, evidence_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Receipt evidence not found")
    return row
