import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional


PUBLICATION_STATUSES = {
    "CREATED",
    "IMAGES_GENERATED",
    "PHOTOS_UPLOADING",
    "PHOTOS_UPLOADED",
    "POST_PUBLISHING",
    "PUBLISHED",
    "PARTIAL_FAILED",
    "FAILED",
}

MEDIA_UPLOAD_STATUSES = {"PENDING", "UPLOADING", "UPLOADED", "FAILED", "SKIPPED"}


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class FacebookMediaItem:
    order: int
    article_id: int
    title: str
    summary: str
    source_name: str
    source_url: str
    image_url: str = ""
    local_image_path: str = ""
    photo_caption: str = ""
    facebook_photo_id: str = ""
    upload_status: str = "PENDING"
    upload_error: str = ""

    def to_dict(self):
        data = asdict(self)
        return {
            "order": data["order"],
            "articleId": data["article_id"],
            "title": data["title"],
            "summary": data["summary"],
            "sourceName": data["source_name"],
            "sourceUrl": data["source_url"],
            "imageUrl": data["image_url"],
            "localImagePath": data["local_image_path"],
            "photoCaption": data["photo_caption"],
            "facebookPhotoId": data["facebook_photo_id"],
            "uploadStatus": data["upload_status"],
            "uploadError": data["upload_error"],
        }


@dataclass
class FacebookPublication:
    id: str
    idempotency_key: str
    page_id: str
    main_caption: str
    media_items: List[FacebookMediaItem] = field(default_factory=list)
    facebook_post_id: str = ""
    status: str = "CREATED"
    created_at: str = field(default_factory=now_iso)
    published_at: str = ""
    last_error: str = ""
    batch_id: str = ""
    publication_date: str = ""
    dry_run: bool = False

    def to_dict(self):
        return {
            "id": self.id,
            "idempotencyKey": self.idempotency_key,
            "pageId": self.page_id,
            "mainCaption": self.main_caption,
            "mediaItems": [item.to_dict() for item in self.media_items],
            "facebookPostId": self.facebook_post_id,
            "status": self.status,
            "createdAt": self.created_at,
            "publishedAt": self.published_at,
            "lastError": self.last_error,
            "batchId": self.batch_id,
            "publicationDate": self.publication_date,
            "dryRun": self.dry_run,
        }


def build_idempotency_key(page_id, publication_date, batch_id):
    return f"facebook-publication:{page_id}:{publication_date}:{batch_id}"


def new_publication(page_id, publication_date, batch_id, main_caption, media_items, dry_run=False):
    return FacebookPublication(
        id=str(uuid.uuid4()),
        idempotency_key=build_idempotency_key(page_id, publication_date, batch_id),
        page_id=page_id,
        main_caption=main_caption,
        media_items=list(media_items),
        status="IMAGES_GENERATED",
        batch_id=batch_id,
        publication_date=publication_date,
        dry_run=bool(dry_run),
    )


class FacebookPublicationRepository:
    def __init__(self, database_path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def connect(self):
        conn = sqlite3.connect(self.database_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connection(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self):
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS facebook_publications (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    page_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    publication_date TEXT NOT NULL,
                    main_caption TEXT NOT NULL,
                    facebook_post_id TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'CREATED',
                    dry_run INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    published_at TEXT DEFAULT '',
                    last_error TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS facebook_media_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    publication_id TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    article_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT DEFAULT '',
                    source_name TEXT DEFAULT '',
                    source_url TEXT DEFAULT '',
                    image_url TEXT DEFAULT '',
                    local_image_path TEXT DEFAULT '',
                    photo_caption TEXT NOT NULL,
                    facebook_photo_id TEXT DEFAULT '',
                    upload_status TEXT NOT NULL DEFAULT 'PENDING',
                    upload_error TEXT DEFAULT '',
                    FOREIGN KEY(publication_id) REFERENCES facebook_publications(id) ON DELETE CASCADE,
                    UNIQUE(publication_id, order_index),
                    UNIQUE(publication_id, article_id)
                );

                CREATE INDEX IF NOT EXISTS idx_facebook_publications_status
                    ON facebook_publications(status);
                CREATE INDEX IF NOT EXISTS idx_facebook_media_publication
                    ON facebook_media_items(publication_id, order_index);
                """
            )

    def get_by_idempotency_key(self, idempotency_key) -> Optional[FacebookPublication]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM facebook_publications WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if not row:
                return None
            media_rows = conn.execute(
                "SELECT * FROM facebook_media_items WHERE publication_id = ? ORDER BY order_index",
                (row["id"],),
            ).fetchall()
        return self._from_rows(row, media_rows)

    def get_by_id(self, publication_id) -> Optional[FacebookPublication]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM facebook_publications WHERE id = ?",
                (str(publication_id),),
            ).fetchone()
            if not row:
                return None
            media_rows = conn.execute(
                "SELECT * FROM facebook_media_items WHERE publication_id = ? ORDER BY order_index",
                (str(publication_id),),
            ).fetchall()
        return self._from_rows(row, media_rows)

    def create(self, publication: FacebookPublication):
        existing = self.get_by_idempotency_key(publication.idempotency_key)
        if existing:
            return existing
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO facebook_publications (
                    id, idempotency_key, page_id, batch_id, publication_date,
                    main_caption, facebook_post_id, status, dry_run,
                    created_at, published_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    publication.id,
                    publication.idempotency_key,
                    publication.page_id,
                    publication.batch_id,
                    publication.publication_date,
                    publication.main_caption,
                    publication.facebook_post_id,
                    publication.status,
                    int(publication.dry_run),
                    publication.created_at,
                    publication.published_at,
                    publication.last_error,
                ),
            )
            for item in publication.media_items:
                conn.execute(
                    """
                    INSERT INTO facebook_media_items (
                        publication_id, order_index, article_id, title, summary,
                        source_name, source_url, image_url, local_image_path,
                        photo_caption, facebook_photo_id, upload_status, upload_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        publication.id,
                        item.order,
                        item.article_id,
                        item.title,
                        item.summary,
                        item.source_name,
                        item.source_url,
                        item.image_url,
                        item.local_image_path,
                        item.photo_caption,
                        item.facebook_photo_id,
                        item.upload_status,
                        item.upload_error,
                    ),
                )
        return publication

    def update_publication(self, publication_id, status=None, facebook_post_id=None, published_at=None, last_error=None):
        if status is not None and status not in PUBLICATION_STATUSES:
            raise ValueError(f"Trạng thái publication không hợp lệ: {status}")
        assignments = []
        values = []
        for column, value in (
            ("status", status),
            ("facebook_post_id", facebook_post_id),
            ("published_at", published_at),
            ("last_error", last_error),
        ):
            if value is not None:
                assignments.append(f"{column} = ?")
                values.append(value)
        if not assignments:
            return
        values.append(publication_id)
        with self.connection() as conn:
            conn.execute(
                f"UPDATE facebook_publications SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

    def update_media(self, publication_id, article_id, facebook_photo_id=None, upload_status=None, upload_error=None):
        if upload_status is not None and upload_status not in MEDIA_UPLOAD_STATUSES:
            raise ValueError(f"Trạng thái media không hợp lệ: {upload_status}")
        assignments = []
        values = []
        for column, value in (
            ("facebook_photo_id", facebook_photo_id),
            ("upload_status", upload_status),
            ("upload_error", upload_error),
        ):
            if value is not None:
                assignments.append(f"{column} = ?")
                values.append(value)
        if not assignments:
            return
        values.extend([publication_id, article_id])
        with self.connection() as conn:
            conn.execute(
                f"UPDATE facebook_media_items SET {', '.join(assignments)} "
                "WHERE publication_id = ? AND article_id = ?",
                values,
            )

    def write_preview(self, publication, output_path, api_preview=None):
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = publication.to_dict()
        if api_preview is not None:
            payload = {"publication": payload, "apiPreview": api_preview}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def get_latest_media_for_article(self, article_id):
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT m.*, p.facebook_post_id, p.main_caption,
                       p.status AS publication_status,
                       p.id AS publication_id
                FROM facebook_media_items AS m
                JOIN facebook_publications AS p ON p.id = m.publication_id
                WHERE m.article_id = ?
                ORDER BY p.created_at DESC
                LIMIT 1
                """,
                (int(article_id),),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _from_rows(row, media_rows):
        items = [
            FacebookMediaItem(
                order=media["order_index"],
                article_id=media["article_id"],
                title=media["title"],
                summary=media["summary"],
                source_name=media["source_name"],
                source_url=media["source_url"],
                image_url=media["image_url"],
                local_image_path=media["local_image_path"],
                photo_caption=media["photo_caption"],
                facebook_photo_id=media["facebook_photo_id"],
                upload_status=media["upload_status"],
                upload_error=media["upload_error"],
            )
            for media in media_rows
        ]
        return FacebookPublication(
            id=row["id"],
            idempotency_key=row["idempotency_key"],
            page_id=row["page_id"],
            main_caption=row["main_caption"],
            media_items=items,
            facebook_post_id=row["facebook_post_id"],
            status=row["status"],
            created_at=row["created_at"],
            published_at=row["published_at"],
            last_error=row["last_error"],
            batch_id=row["batch_id"],
            publication_date=row["publication_date"],
            dry_run=bool(row["dry_run"]),
        )
