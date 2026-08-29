from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from google.api_core.exceptions import GoogleAPIError, NotFound
from google.cloud import storage

from app.core.config import get_settings


@dataclass(frozen=True)
class DocumentStorageStatus:
    provider: str
    configured: bool
    reachable: bool | None
    bucket: str | None
    message: str
    checked_at: datetime


class DocumentStorageError(RuntimeError):
    pass


class GcsDocumentStorage:
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket_name = settings.document_storage_bucket.strip()
        self.prefix = settings.document_storage_prefix.strip().strip("/") or "imob-erp"

    @property
    def configured(self) -> bool:
        return bool(self.bucket_name)

    def status(self, *, probe: bool = False) -> DocumentStorageStatus:
        if not self.configured:
            return DocumentStorageStatus(
                provider="gcs",
                configured=False,
                reachable=None,
                bucket=None,
                message="Bucket de documentos ainda não configurado.",
                checked_at=datetime.now(timezone.utc),
            )
        if not probe:
            return DocumentStorageStatus(
                provider="gcs",
                configured=True,
                reachable=None,
                bucket=self.bucket_name,
                message="Bucket configurado. Execute o teste para validar acesso da service account.",
                checked_at=datetime.now(timezone.utc),
            )
        try:
            client = storage.Client()
            bucket = client.bucket(self.bucket_name)
            bucket.reload()
            return DocumentStorageStatus(
                provider="gcs",
                configured=True,
                reachable=True,
                bucket=self.bucket_name,
                message="Storage de documentos acessível pela service account do Cloud Run.",
                checked_at=datetime.now(timezone.utc),
            )
        except NotFound:
            message = "Bucket configurado não foi encontrado."
        except GoogleAPIError as exc:
            message = f"Não foi possível validar o bucket: {exc.__class__.__name__}."
        except Exception as exc:  # credenciais/ambiente local
            message = f"Não foi possível validar o storage: {exc.__class__.__name__}."
        return DocumentStorageStatus(
            provider="gcs",
            configured=True,
            reachable=False,
            bucket=self.bucket_name,
            message=message,
            checked_at=datetime.now(timezone.utc),
        )

    def object_name(self, *, organization_id: str, contract_code: str, filename: str) -> str:
        safe_code = contract_code.replace("/", "-").replace(" ", "-")
        safe_filename = filename.replace("/", "-")
        return f"{self.prefix}/{organization_id}/contracts/{safe_code}/{safe_filename}"

    def upload_bytes(self, *, object_name: str, content: bytes, content_type: str) -> str:
        if not self.configured:
            raise DocumentStorageError("Bucket de documentos ainda não configurado.")
        try:
            client = storage.Client()
            bucket = client.bucket(self.bucket_name)
            blob = bucket.blob(object_name)
            blob.upload_from_string(content, content_type=content_type)
            return f"gs://{self.bucket_name}/{object_name}"
        except Exception as exc:
            raise DocumentStorageError(f"Falha ao arquivar documento no storage: {exc.__class__.__name__}.") from exc

    def download_bytes(self, reference: str) -> bytes:
        if not self.configured:
            raise DocumentStorageError("Bucket de documentos ainda não configurado.")
        prefix = f"gs://{self.bucket_name}/"
        if not reference.startswith(prefix):
            raise DocumentStorageError("Referência de documento não pertence ao bucket configurado.")
        object_name = reference[len(prefix):]
        try:
            client = storage.Client()
            return client.bucket(self.bucket_name).blob(object_name).download_as_bytes()
        except Exception as exc:
            raise DocumentStorageError(f"Falha ao recuperar documento do storage: {exc.__class__.__name__}.") from exc


def get_document_storage() -> GcsDocumentStorage:
    return GcsDocumentStorage()
