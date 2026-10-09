import json

from openai import AzureOpenAI

from app.config import Settings
from app.services.blob_url import redact_secrets
from app.services.errors import ProcessingError

_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_NUMBER = {"anyOf": [{"type": "number"}, {"type": "null"}]}

RECEIPT_JSON_SCHEMA = {
    "name": "terminal_receipt",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "mid": {**_NULLABLE_STRING, "description": "Merchant ID printed on the terminal slip"},
            "tid": {**_NULLABLE_STRING, "description": "Terminal ID"},
            "city": {**_NULLABLE_STRING, "description": "City"},
            "country": {**_NULLABLE_STRING, "description": "Country"},
            "txn_amount": {
                **_NULLABLE_NUMBER,
                "description": "Transaction amount as a number, without currency symbols",
            },
            "currency": {**_NULLABLE_STRING, "description": "ISO 4217 currency code, three letters"},
            "txn_date": {**_NULLABLE_STRING, "description": "Transaction date and time in ISO-8601"},
            "txn_reference": {**_NULLABLE_STRING, "description": "RRN or other transaction reference"},
            "auth_code": {**_NULLABLE_STRING, "description": "Authorization code"},
            "card_last4": {**_NULLABLE_STRING, "description": "Last four digits of the card"},
            "scheme": {**_NULLABLE_STRING, "description": "Card scheme such as Visa or Mastercard"},
            "outlet_address": {**_NULLABLE_STRING, "description": "Outlet or merchant address printed on the slip"},
            "merchant_name": {**_NULLABLE_STRING, "description": "Name of the merchant"},
            "location_id": {**_NULLABLE_STRING, "description": "Location ID if printed on the slip"},
            "effective_data": {**_NULLABLE_STRING, "description": "Effective date/time of the transaction in ISO-8601"},
            "confidence": {"type": "number", "description": "Overall extraction confidence from 0 to 1"},
        },
        "required": [
            "mid",
            "tid",
            "city",
            "country",
            "txn_amount",
            "currency",
            "txn_date",
            "txn_reference",
            "auth_code",
            "card_last4",
            "scheme",
            "outlet_address",
            "merchant_name",
            "location_id",
            "effective_data",
            "confidence",
        ],
    },
}

_SYSTEM_PROMPT = """You extract fields from a payment terminal transaction slip.
Use only the OCR text. Leave a field null when it is not printed. Do not guess or calculate missing values.
txn_amount is a JSON number. currency is a 3-letter ISO code such as AED.
txn_date and effective_data should be ISO-8601 when the slip has both a date and a time.
card_last4 is the last four digits only. scheme is the card network.
confidence is your overall confidence from 0 to 1.
"""


class ReceiptExtractor:
    def __init__(self, settings: Settings):
        self._settings = settings

    def extract(self, ocr_text: str) -> dict:
        if not (
            self._settings.azure_openai_endpoint
            and self._settings.azure_openai_api_key
            and self._settings.azure_openai_deployment
        ):
            raise ProcessingError("extraction", "Azure OpenAI is not configured")

        client = AzureOpenAI(
            azure_endpoint=self._settings.azure_openai_endpoint,
            api_key=self._settings.azure_openai_api_key,
            api_version=self._settings.azure_openai_api_version,
        )
        content = self._complete(client, ocr_text)
        return _parse_json(content)

    def _complete(self, client: AzureOpenAI, ocr_text: str) -> str:
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": ocr_text},
        ]
        try:
            response = client.chat.completions.create(
                model=self._settings.azure_openai_deployment,
                temperature=0,
                messages=messages,
                response_format={"type": "json_schema", "json_schema": RECEIPT_JSON_SCHEMA},
            )
        except Exception as exc:
            if not _schema_unsupported(exc):
                raise ProcessingError("extraction", redact_secrets(str(exc))) from exc
            try:
                response = client.chat.completions.create(
                    model=self._settings.azure_openai_deployment,
                    temperature=0,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
            except Exception as retry_exc:
                raise ProcessingError("extraction", redact_secrets(str(retry_exc))) from retry_exc

        message = response.choices[0].message.content if response.choices else None
        if not message:
            raise ProcessingError("extraction", "Azure OpenAI returned an empty extraction")
        return message


def _schema_unsupported(exc: Exception) -> bool:
    text = str(exc).lower()
    return "response_format" in text or "json_schema" in text


def _parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProcessingError("extraction", "Azure OpenAI returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ProcessingError("extraction", "Azure OpenAI returned a JSON value that is not an object")
    return payload
