from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from google.api_core.exceptions import GoogleAPIError, NotFound
from google.cloud import storage
from sqlalchemy import text

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
        except Exception as exc:
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

    def inspection_object_name(self, *, organization_id: str, inspection_code: str, filename: str) -> str:
        safe_code = inspection_code.replace("/", "-").replace(" ", "-")
        safe_filename = filename.replace("..", "-").lstrip("/")
        return f"{self.prefix}/{organization_id}/inspections/{safe_code}/{safe_filename}"

    def property_photo_object_name(self, *, organization_id: str, property_code: str, photo_id: str, filename: str) -> str:
        safe_code = property_code.replace("/", "-").replace(" ", "-")
        safe_filename = filename.replace("..", "-").replace("/", "-").replace("\\", "-")
        return f"{self.prefix}/{organization_id}/properties/{safe_code}/photos/{photo_id}-{safe_filename}"

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
            return storage.Client().bucket(self.bucket_name).blob(object_name).download_as_bytes()
        except Exception as exc:
            raise DocumentStorageError(f"Falha ao recuperar documento do storage: {exc.__class__.__name__}.") from exc

    def delete_reference(self, reference: str) -> None:
        if not self.configured:
            raise DocumentStorageError("Bucket de documentos ainda não configurado.")
        prefix = f"gs://{self.bucket_name}/"
        if not reference.startswith(prefix):
            raise DocumentStorageError("Referência de documento não pertence ao bucket configurado.")
        object_name = reference[len(prefix):]
        try:
            storage.Client().bucket(self.bucket_name).blob(object_name).delete()
        except NotFound:
            return
        except Exception as exc:
            raise DocumentStorageError(f"Falha ao excluir documento do storage: {exc.__class__.__name__}.") from exc


class DatabaseDocumentStorage:
    reference_prefix = "db://document-storage/"

    @staticmethod
    def _engine():
        from app.core.database import engine

        return engine

    @property
    def configured(self) -> bool:
        return self._engine() is not None

    def status(self, *, probe: bool = False) -> DocumentStorageStatus:
        if not self.configured:
            return DocumentStorageStatus(
                provider="database",
                configured=False,
                reachable=None,
                bucket=None,
                message="Storage persistente indisponível porque o banco não está configurado.",
                checked_at=datetime.now(timezone.utc),
            )
        if not probe:
            return DocumentStorageStatus(
                provider="database",
                configured=True,
                reachable=None,
                bucket=None,
                message="Storage persistente ativo no PostgreSQL/Neon.",
                checked_at=datetime.now(timezone.utc),
            )
        try:
            engine = self._engine()
            assert engine is not None
            with engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM document_storage_objects LIMIT 1"))
            return DocumentStorageStatus(
                provider="database",
                configured=True,
                reachable=True,
                bucket=None,
                message="Storage persistente no PostgreSQL/Neon acessível.",
                checked_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            return DocumentStorageStatus(
                provider="database",
                configured=True,
                reachable=False,
                bucket=None,
                message=f"Não foi possível validar o storage persistente: {exc.__class__.__name__}.",
                checked_at=datetime.now(timezone.utc),
            )

    def upload_bytes(self, *, object_name: str, content: bytes, content_type: str) -> str:
        engine = self._engine()
        if engine is None:
            raise DocumentStorageError("Storage persistente no banco não está configurado.")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO document_storage_objects
                            (object_name, content_type, size_bytes, content, created_at, updated_at)
                        VALUES
                            (:object_name, :content_type, :size_bytes, :content, now(), now())
                        ON CONFLICT (object_name) DO UPDATE SET
                            content_type = EXCLUDED.content_type,
                            size_bytes = EXCLUDED.size_bytes,
                            content = EXCLUDED.content,
                            updated_at = now()
                        """
                    ),
                    {
                        "object_name": object_name,
                        "content_type": content_type,
                        "size_bytes": len(content),
                        "content": content,
                    },
                )
            return f"{self.reference_prefix}{object_name}"
        except Exception as exc:
            raise DocumentStorageError(f"Falha ao arquivar documento no banco: {exc.__class__.__name__}.") from exc

    def download_bytes(self, reference: str) -> bytes:
        if not reference.startswith(self.reference_prefix):
            raise DocumentStorageError("Referência de documento não pertence ao storage persistente do banco.")
        engine = self._engine()
        if engine is None:
            raise DocumentStorageError("Storage persistente no banco não está configurado.")
        object_name = reference[len(self.reference_prefix):]
        try:
            with engine.connect() as connection:
                value = connection.execute(
                    text("SELECT content FROM document_storage_objects WHERE object_name = :object_name"),
                    {"object_name": object_name},
                ).scalar_one_or_none()
            if value is None:
                raise DocumentStorageError("Documento não encontrado no storage persistente.")
            return bytes(value)
        except DocumentStorageError:
            raise
        except Exception as exc:
            raise DocumentStorageError(f"Falha ao recuperar documento do banco: {exc.__class__.__name__}.") from exc

    def delete_reference(self, reference: str) -> None:
        if not reference.startswith(self.reference_prefix):
            raise DocumentStorageError("Referência de documento não pertence ao storage persistente do banco.")
        engine = self._engine()
        if engine is None:
            raise DocumentStorageError("Storage persistente no banco não está configurado.")
        object_name = reference[len(self.reference_prefix):]
        try:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM document_storage_objects WHERE object_name = :object_name"),
                    {"object_name": object_name},
                )
        except Exception as exc:
            raise DocumentStorageError(f"Falha ao excluir documento do banco: {exc.__class__.__name__}.") from exc


class HybridDocumentStorage:
    def __init__(self) -> None:
        self.gcs = GcsDocumentStorage()
        self.database = DatabaseDocumentStorage()

    @property
    def configured(self) -> bool:
        return self.gcs.configured or self.database.configured

    def status(self, *, probe: bool = False) -> DocumentStorageStatus:
        if self.gcs.configured:
            return self.gcs.status(probe=probe)
        return self.database.status(probe=probe)

    def object_name(self, *, organization_id: str, contract_code: str, filename: str) -> str:
        return self.gcs.object_name(organization_id=organization_id, contract_code=contract_code, filename=filename)

    def inspection_object_name(self, *, organization_id: str, inspection_code: str, filename: str) -> str:
        return self.gcs.inspection_object_name(organization_id=organization_id, inspection_code=inspection_code, filename=filename)

    def property_photo_object_name(self, *, organization_id: str, property_code: str, photo_id: str, filename: str) -> str:
        return self.gcs.property_photo_object_name(
            organization_id=organization_id,
            property_code=property_code,
            photo_id=photo_id,
            filename=filename,
        )

    def upload_bytes(self, *, object_name: str, content: bytes, content_type: str) -> str:
        if self.gcs.configured:
            return self.gcs.upload_bytes(object_name=object_name, content=content, content_type=content_type)
        return self.database.upload_bytes(object_name=object_name, content=content, content_type=content_type)

    def download_bytes(self, reference: str) -> bytes:
        if reference.startswith(DatabaseDocumentStorage.reference_prefix):
            return self.database.download_bytes(reference)
        if reference.startswith("gs://"):
            return self.gcs.download_bytes(reference)
        raise DocumentStorageError("Referência de documento possui formato desconhecido.")

    def delete_reference(self, reference: str) -> None:
        if reference.startswith(DatabaseDocumentStorage.reference_prefix):
            self.database.delete_reference(reference)
            return
        if reference.startswith("gs://"):
            self.gcs.delete_reference(reference)
            return
        raise DocumentStorageError("Referência de documento possui formato desconhecido.")


def get_document_storage() -> HybridDocumentStorage:
    return HybridDocumentStorage()
