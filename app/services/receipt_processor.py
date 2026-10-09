import logging
import uuid
from datetime import datetime, timezone

from app.models.receipt_evidence import ReceiptEvidence
from app.services.blob_url import redact_secrets
from app.services.document_intelligence import DocumentIntelligenceOcr
from app.services.errors import ProcessingError
from app.services.mapping import map_extraction
from app.services.receipt_extractor import ReceiptExtractor

logger = logging.getLogger(__name__)


class ReceiptProcessor:
    def __init__(self, ocr: DocumentIntelligenceOcr, extractor: ReceiptExtractor, session_factory):
        self._ocr = ocr
        self._extractor = extractor
        self._session_factory = session_factory

    def run(self, evidence_id: uuid.UUID, access_url: str) -> None:
        session = self._session_factory()
        try:
            row = session.get(ReceiptEvidence, evidence_id)
            if row is None:
                logger.warning("receipt evidence %s disappeared before OCR", evidence_id)
                return
            try:
                ocr_text = self._ocr.extract_text(access_url)
                raw = self._extractor.extract(ocr_text)
                for column, value in map_extraction(raw).items():
                    setattr(row, column, value)
                row.extracted_data = raw
                row.evidence_ready = True
            except ProcessingError as exc:
                _mark_failed(row, exc.stage, redact_secrets(str(exc)))
            except Exception as exc:
                _mark_failed(row, "processing", redact_secrets(str(exc)))
            row.updated_at = datetime.now(timezone.utc)
            session.commit()
        finally:
            session.close()


def _mark_failed(row: ReceiptEvidence, stage: str, message: str) -> None:
    row.evidence_ready = False
    row.extracted_data = {"error": message, "stage": stage}
    logger.info("receipt evidence %s failed during %s", row.id, stage)
