"""Elasticsearch Backend — full-text search for technical documentation.

Indexes and searches project documentation, docstrings, and comments
using Elasticsearch full-text capabilities.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    from elasticsearch import Elasticsearch
    ES_AVAILABLE = True
except ImportError:
    ES_AVAILABLE = False

logger = logging.getLogger(__name__)


class ElasticsearchBackend:
    """Elasticsearch backend for technical documentation search."""

    INDEX_NAME = "nexus_docs"

    def __init__(self, hosts: list[str] | None = None) -> None:
        if not ES_AVAILABLE:
            raise ImportError(
                "elasticsearch is required. Install: pip install elasticsearch"
            )
        self._hosts = hosts or ["http://localhost:9200"]
        self._client = Elasticsearch(hosts=self._hosts)
        self._connected = True

        try:
            self.ensure_index()
        except Exception as exc:
            logger.warning("Elasticsearch init failed: %s", exc)
            self._connected = False

    def ensure_index(self) -> None:
        """Create index with mappings if it doesn't exist."""
        if self._client.indices.exists(index=self.INDEX_NAME):
            return

        self._client.indices.create(
            index=self.INDEX_NAME,
            body={
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                },
                "mappings": {
                    "properties": {
                        "content": {"type": "text"},
                        "title": {"type": "keyword"},
                        "source": {"type": "keyword"},
                        "file_path": {"type": "keyword"},
                        "doc_type": {"type": "keyword"},
                        "timestamp": {"type": "date"},
                    }
                },
            },
        )
        logger.info("Created Elasticsearch index: %s", self.INDEX_NAME)

    def index_document(
        self,
        doc_id: str,
        content: str,
        title: str = "",
        source: str = "",
        file_path: str = "",
        doc_type: str = "documentation",
    ) -> bool:
        """Index a document.

        Args:
            doc_id: Unique document ID.
            content: Document content.
            title: Document title.
            source: Source identifier.
            file_path: Path to source file.
            doc_type: Document type.

        Returns:
            True if indexed successfully.
        """
        if not self._connected:
            return False
        try:
            self._client.index(
                index=self.INDEX_NAME,
                id=doc_id,
                body={
                    "content": content,
                    "title": title,
                    "source": source,
                    "file_path": file_path,
                    "doc_type": doc_type,
                    "timestamp": "now",
                },
            )
            return True
        except Exception as exc:
            logger.warning("ES index failed: %s", exc)
            return False

    def search(
        self,
        query: str,
        top_k: int = 10,
        doc_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Full-text search.

        Args:
            query: Search query.
            top_k: Number of results.
            doc_type: Filter by document type.

        Returns:
            List of matching documents.
        """
        if not self._connected:
            return []
        try:
            search_body = {
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": ["content^2", "title"],
                    }
                },
                "size": top_k,
            }

            if doc_type:
                search_body["query"] = {
                    "bool": {
                        "must": [
                            search_body["query"],
                            {"term": {"doc_type": doc_type}},
                        ]
                    }
                }

            results = self._client.search(index=self.INDEX_NAME, body=search_body)
            return [
                {
                    "id": hit["_id"],
                    "score": hit["_score"],
                    "content": hit["_source"].get("content", "")[:500],
                    "title": hit["_source"].get("title", ""),
                    "source": hit["_source"].get("source", ""),
                }
                for hit in results["hits"]["hits"]
            ]
        except Exception as exc:
            logger.warning("ES search failed: %s", exc)
            return []

    def delete_document(self, doc_id: str) -> bool:
        """Delete a document by ID."""
        if not self._connected:
            return False
        try:
            self._client.delete(index=self.INDEX_NAME, id=doc_id)
            return True
        except Exception as exc:
            logger.warning("ES delete failed: %s", exc)
            return False

    def index_markdown_directory(self, directory: str | Path) -> int:
        """Index all .md files in a directory.

        Args:
            directory: Path to directory.

        Returns:
            Number of files indexed.
        """
        dir_path = Path(directory)
        count = 0
        for md_file in dir_path.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                self.index_document(
                    doc_id=f"md:{md_file.relative_to(dir_path)}",
                    content=content,
                    title=md_file.name,
                    file_path=str(md_file),
                    doc_type="markdown",
                )
                count += 1
            except Exception as exc:
                logger.warning("Failed to index %s: %s", md_file, exc)
        logger.info("Indexed %d markdown files from %s", count, directory)
        return count
