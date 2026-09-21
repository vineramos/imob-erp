from __future__ import annotations

import logging

from sqlalchemy import text

from app.integrations.document_storage import GcsDocumentStorage

logger = logging.getLogger(__name__)
LOCK_KEY = "imob-document-storage-migration-v1"


def migrate_database_documents(*, batch_size: int = 100) -> tuple[int, int]:
    """Copia objetos do PostgreSQL para GCS e remove o binário após sucesso.

    As referências `db://` são preservadas. O storage híbrido passa a resolvê-las
    no GCS e mantém fallback para o banco durante migrações parciais.
    """
    from app.core.database import engine

    storage = GcsDocumentStorage()
    if engine is None or not storage.configured:
        return 0, 0

    migrated = 0
    failed = 0
    cursor = ""
    with engine.connect() as connection:
        locked = bool(connection.execute(text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": LOCK_KEY}).scalar())
        if not locked:
            logger.info("Migração de documentos já está sendo executada por outra instância.")
            return 0, 0
        try:
            while True:
                rows = connection.execute(
                    text(
                        """
                        SELECT object_name, content_type, content
                        FROM document_storage_objects
                        WHERE object_name > :cursor
                        ORDER BY object_name
                        LIMIT :batch_size
                        """
                    ),
                    {"cursor": cursor, "batch_size": batch_size},
                ).all()
                if not rows:
                    break
                for row in rows:
                    cursor = row.object_name
                    try:
                        storage.upload_bytes(
                            object_name=row.object_name,
                            content=bytes(row.content),
                            content_type=row.content_type,
                        )
                        with engine.begin() as delete_connection:
                            delete_connection.execute(
                                text("DELETE FROM document_storage_objects WHERE object_name = :object_name"),
                                {"object_name": row.object_name},
                            )
                        migrated += 1
                    except Exception:
                        failed += 1
                        logger.exception("Falha ao migrar objeto %s; original mantido no banco.", row.object_name)
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": LOCK_KEY})

    logger.info("Migração de documentos concluída: %s migrados, %s falhas.", migrated, failed)
    return migrated, failed


if __name__ == "__main__":
    migrate_database_documents()
