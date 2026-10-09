from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.credentials import AzureKeyCredential

from app.config import Settings
from app.services.blob_url import redact_secrets
from app.services.errors import ProcessingError


class DocumentIntelligenceOcr:
    """OCR step of the ARGUS hybrid pipeline. prebuilt-read returns slip text; field mapping is done by the model."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def extract_text(self, url: str) -> str:
        if not self._settings.document_intelligence_endpoint or not self._settings.document_intelligence_key:
            raise ProcessingError("ocr", "Document Intelligence is not configured")

        try:
            client = DocumentIntelligenceClient(
                endpoint=self._settings.document_intelligence_endpoint,
                credential=AzureKeyCredential(self._settings.document_intelligence_key),
            )
            poller = client.begin_analyze_document("prebuilt-read", AnalyzeDocumentRequest(url_source=url))
            result = poller.result()
        except ProcessingError:
            raise
        except Exception as exc:
            raise ProcessingError("ocr", redact_secrets(str(exc))) from exc

        content = (result.content or "").strip()
        if not content:
            raise ProcessingError("ocr", "Document Intelligence returned no text")
        return content
