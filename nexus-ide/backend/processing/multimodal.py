"""Multi-Modal Processing System for Text, Image, Audio, and Video.

Implements unified processing pipeline with modality-specific processors,
cross-modal fusion, and integrated understanding.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class ModalityType(str, Enum):
    """Types of modalities."""
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    CODE = "code"
    TABLE = "table"
    CHART = "chart"


class ProcessingStatus(str, Enum):
    """Processing status tracking."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FusionStrategy(str, Enum):
    """Cross-modal fusion strategies."""
    EARLY_FUSION = "early_fusion"  # Combine features early
    LATE_FUSION = "late_fusion"    # Combine results late
    HYBRID_FUSION = "hybrid_fusion"  # Mix of early and late
    ATTENTION_FUSION = "attention_fusion"  # Attention-based fusion


@dataclass
class MediaContent:
    """Unified media content representation."""
    content_id: str = field(default_factory=lambda: f"content-{uuid.uuid4().hex[:12]}")
    modality: ModalityType = ModalityType.TEXT
    raw_data: str | bytes = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # Content properties
    mime_type: str = ""
    size_bytes: int = 0
    duration: float | None = None  # For audio/video
    dimensions: tuple[int, int] | None = None  # For images/video
    
    # Processing metadata
    extracted_features: dict[str, Any] = field(default_factory=dict)
    processed_data: dict[str, Any] | None = None
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    
    # Quality metrics
    quality_score: float = 0.0  # 0.0-1.0
    confidence: float = 0.0  # 0.0-1.0
    
    # Timestamps
    created_at: float = field(default_factory=time.time)
    processed_at: float | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "modality": self.modality.value,
            "raw_data": self.raw_data if isinstance(self.raw_data, str) else base64.b64encode(self.raw_data).decode(),
            "metadata": self.metadata,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "duration": self.duration,
            "dimensions": self.dimensions,
            "extracted_features": self.extracted_features,
            "processed_data": self.processed_data,
            "processing_status": self.processing_status.value,
            "quality_score": self.quality_score,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "processed_at": self.processed_at,
        }


@dataclass
class ProcessingResult:
    """Result from modality processing."""
    result_id: str = field(default_factory=lambda: f"result-{uuid.uuid4().hex[:12]}")
    content_id: str = ""
    modality: ModalityType = ModalityType.TEXT
    processor_id: str = ""
    
    # Processing results
    extracted_features: dict[str, Any] = field(default_factory=dict)
    structured_data: dict[str, Any] = field(default_factory=dict)
    embeddings: list[float] | None = None
    classifications: dict[str, float] = field(default_factory=dict)
    
    # Quality metrics
    processing_time: float = 0.0
    quality_score: float = 0.0
    confidence: float = 0.0
    
    # Errors and warnings
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    
    # Metadata
    processor_version: str = ""
    processing_parameters: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "content_id": self.content_id,
            "modality": self.modality.value,
            "processor_id": self.processor_id,
            "extracted_features": self.extracted_features,
            "structured_data": self.structured_data,
            "embeddings": self.embeddings,
            "classifications": self.classifications,
            "processing_time": self.processing_time,
            "quality_score": self.quality_score,
            "confidence": self.confidence,
            "errors": self.errors,
            "warnings": self.warnings,
            "processor_version": self.processor_version,
            "processing_parameters": self.processing_parameters,
            "timestamp": self.timestamp,
        }


@dataclass
class FusionResult:
    """Result from cross-modal fusion."""
    fusion_id: str = field(default_factory=lambda: f"fusion-{uuid.uuid4().hex[:12]}")
    content_ids: list[str] = field(default_factory=list)
    strategy: FusionStrategy = FusionStrategy.LATE_FUSION
    
    # Fusion results
    unified_features: dict[str, Any] = field(default_factory=dict)
    unified_embeddings: list[float] | None = None
    cross_modal_insights: list[str] = field(default_factory=list)
    
    # Quality metrics
    fusion_quality: float = 0.0
    consistency_score: float = 0.0
    completeness_score: float = 0.0
    
    # Processing metadata
    processing_time: float = 0.0
    fusion_parameters: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "fusion_id": self.fusion_id,
            "content_ids": self.content_ids,
            "strategy": self.strategy.value,
            "unified_features": self.unified_features,
            "unified_embeddings": self.unified_embeddings,
            "cross_modal_insights": self.cross_modal_insights,
            "fusion_quality": self.fusion_quality,
            "consistency_score": self.consistency_score,
            "completeness_score": self.completeness_score,
            "processing_time": self.processing_time,
            "fusion_parameters": self.fusion_parameters,
            "timestamp": self.timestamp,
        }


class TextProcessor:
    """Text processing and analysis."""
    
    def __init__(self, model_client):
        self.model_client = model_client
        self.processor_id = "text_processor_v1"
        
    async def process(self, content: MediaContent) -> ProcessingResult:
        """Process text content."""
        start_time = time.time()
        
        try:
            content.processing_status = ProcessingStatus.PROCESSING
            
            # Extract text features
            text = content.raw_data if isinstance(content.raw_data, str) else content.raw_data.decode()
            
            # Basic text analysis
            features = {
                "length": len(text),
                "word_count": len(text.split()),
                "sentence_count": text.count('.') + text.count('!') + text.count('?'),
                "language": self._detect_language(text),
                "sentiment": self._analyze_sentiment(text),
                "entities": self._extract_entities(text),
                "keywords": self._extract_keywords(text),
                "readability": self._calculate_readability(text),
            }
            
            # Generate embeddings
            embeddings = await self._generate_embeddings(text)
            
            # Classify content
            classifications = await self._classify_text(text)
            
            # Extract structured data
            structured_data = {
                "summary": await self._generate_summary(text),
                "topics": await self._extract_topics(text),
                "intent": await self._detect_intent(text),
            }
            
            processing_time = time.time() - start_time
            
            result = ProcessingResult(
                content_id=content.content_id,
                modality=ModalityType.TEXT,
                processor_id=self.processor_id,
                extracted_features=features,
                structured_data=structured_data,
                embeddings=embeddings,
                classifications=classifications,
                processing_time=processing_time,
                quality_score=self._calculate_quality_score(features),
                confidence=0.8,
                processor_version="1.0",
            )
            
            content.processed_data = result.to_dict()
            content.processing_status = ProcessingStatus.COMPLETED
            content.processed_at = time.time()
            
            return result
            
        except Exception as exc:
            content.processing_status = ProcessingStatus.FAILED
            
            return ProcessingResult(
                content_id=content.content_id,
                modality=ModalityType.TEXT,
                processor_id=self.processor_id,
                processing_time=time.time() - start_time,
                errors=[str(exc)],
                confidence=0.0,
            )
            
    def _detect_language(self, text: str) -> str:
        """Simple language detection."""
        # In real implementation, would use proper language detection
        if any(word in text.lower() for word in ["the", "and", "is", "to"]):
            return "en"
        elif any(word in text.lower() for word in ["o", "e", "é", "de"]):
            return "pt"
        else:
            return "unknown"
            
    def _analyze_sentiment(self, text: str) -> dict[str, float]:
        """Simple sentiment analysis."""
        positive_words = ["good", "great", "excellent", "amazing", "wonderful"]
        negative_words = ["bad", "terrible", "awful", "horrible", "worst"]
        
        text_lower = text.lower()
        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)
        
        total = positive_count + negative_count
        if total == 0:
            return {"positive": 0.5, "negative": 0.5, "neutral": 1.0}
            
        return {
            "positive": positive_count / total,
            "negative": negative_count / total,
            "neutral": 0.0,
        }
        
    def _extract_entities(self, text: str) -> list[dict[str, str]]:
        """Simple entity extraction."""
        # In real implementation, would use NER models
        entities = []
        
        # Extract emails
        import re
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
        for email in emails:
            entities.append({"type": "email", "value": email})
            
        # Extract URLs
        urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', text)
        for url in urls:
            entities.append({"type": "url", "value": url})
            
        return entities
        
    def _extract_keywords(self, text: str) -> list[str]:
        """Simple keyword extraction."""
        # Remove common words and get most frequent
        common_words = {"the", "and", "is", "to", "a", "in", "that", "it", "with", "for"}
        words = text.lower().split()
        filtered_words = [word for word in words if word not in common_words and len(word) > 3]
        
        # Count frequency
        word_counts = {}
        for word in filtered_words:
            word_counts[word] = word_counts.get(word, 0) + 1
            
        # Return top 10
        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        return [word for word, count in sorted_words[:10]]
        
    def _calculate_readability(self, text: str) -> float:
        """Calculate readability score."""
        sentences = text.count('.') + text.count('!') + text.count('?')
        words = len(text.split())
        
        if sentences == 0:
            return 0.0
            
        avg_words_per_sentence = words / sentences
        # Simple readability score (lower is better)
        readability = max(0.0, 1.0 - (avg_words_per_sentence - 15) / 30)
        return readability
        
    async def _generate_embeddings(self, text: str) -> list[float]:
        """Generate text embeddings."""
        # In real implementation, would use embedding models
        # Mock embeddings for demonstration
        hash_obj = hashlib.md5(text.encode())
        hash_hex = hash_obj.hexdigest()
        
        # Convert hash to float embeddings
        embeddings = []
        for i in range(0, len(hash_hex), 2):
            byte_pair = hash_hex[i:i+2]
            embeddings.append(int(byte_pair, 16) / 255.0)
            
        return embeddings[:128]  # Return 128-dimensional embeddings
        
    async def _classify_text(self, text: str) -> dict[str, float]:
        """Classify text content."""
        # Simple classification based on keywords
        categories = {
            "technical": ["code", "programming", "algorithm", "system", "database"],
            "business": ["market", "revenue", "customer", "strategy", "profit"],
            "academic": ["research", "study", "analysis", "theory", "method"],
            "creative": ["design", "art", "creative", "innovative", "inspire"],
        }
        
        text_lower = text.lower()
        classifications = {}
        
        for category, keywords in categories.items():
            score = sum(1 for keyword in keywords if keyword in text_lower) / len(keywords)
            classifications[category] = score
            
        return classifications
        
    async def _generate_summary(self, text: str) -> str:
        """Generate text summary."""
        # Simple extractive summary (first sentence)
        sentences = text.split('.')
        if sentences:
            return sentences[0].strip() + "."
        return ""
        
    async def _extract_topics(self, text: str) -> list[str]:
        """Extract main topics."""
        # Use keywords as topics
        keywords = self._extract_keywords(text)
        return keywords[:5]
        
    async def _detect_intent(self, text: str) -> str:
        """Detect user intent."""
        question_words = ["what", "how", "why", "when", "where", "who"]
        command_words = ["please", "can you", "could you", "help me"]
        
        text_lower = text.lower()
        
        if any(word in text_lower for word in question_words):
            return "question"
        elif any(word in text_lower for word in command_words):
            return "request"
        else:
            return "statement"
            
    def _calculate_quality_score(self, features: dict[str, Any]) -> float:
        """Calculate text quality score."""
        score = 0.0
        
        # Length score (prefer reasonable length)
        length = features["length"]
        if 50 <= length <= 1000:
            score += 0.3
        elif 1000 < length <= 5000:
            score += 0.2
            
        # Readability score
        readability = features["readability"]
        score += readability * 0.3
        
        # Language detection
        if features["language"] != "unknown":
            score += 0.2
            
        # Entity extraction
        if features["entities"]:
            score += 0.2
            
        return min(1.0, score)


class ImageProcessor:
    """Image processing and analysis."""
    
    def __init__(self, model_client):
        self.model_client = model_client
        self.processor_id = "image_processor_v1"
        
    async def process(self, content: MediaContent) -> ProcessingResult:
        """Process image content."""
        start_time = time.time()
        
        try:
            content.processing_status = ProcessingStatus.PROCESSING
            
            # Extract image features
            features = {
                "format": content.mime_type,
                "size": content.size_bytes,
                "dimensions": content.dimensions,
                "aspect_ratio": self._calculate_aspect_ratio(content.dimensions),
                "color_histogram": self._extract_color_histogram(content.raw_data),
                "edge_density": self._calculate_edge_density(content.raw_data),
                "brightness": self._calculate_brightness(content.raw_data),
                "contrast": self._calculate_contrast(content.raw_data),
            }
            
            # Generate embeddings
            embeddings = await self._generate_image_embeddings(content.raw_data)
            
            # Classify content
            classifications = await self._classify_image(content.raw_data)
            
            # Extract structured data
            structured_data = {
                "objects": await self._detect_objects(content.raw_data),
                "scenes": await self._classify_scene(content.raw_data),
                "text": await self._extract_text_from_image(content.raw_data),
                "faces": await self._detect_faces(content.raw_data),
            }
            
            processing_time = time.time() - start_time
            
            result = ProcessingResult(
                content_id=content.content_id,
                modality=ModalityType.IMAGE,
                processor_id=self.processor_id,
                extracted_features=features,
                structured_data=structured_data,
                embeddings=embeddings,
                classifications=classifications,
                processing_time=processing_time,
                quality_score=self._calculate_image_quality_score(features),
                confidence=0.7,
                processor_version="1.0",
            )
            
            content.processed_data = result.to_dict()
            content.processing_status = ProcessingStatus.COMPLETED
            content.processed_at = time.time()
            
            return result
            
        except Exception as exc:
            content.processing_status = ProcessingStatus.FAILED
            
            return ProcessingResult(
                content_id=content.content_id,
                modality=ModalityType.IMAGE,
                processor_id=self.processor_id,
                processing_time=time.time() - start_time,
                errors=[str(exc)],
                confidence=0.0,
            )
            
    def _calculate_aspect_ratio(self, dimensions: tuple[int, int] | None) -> float:
        """Calculate aspect ratio."""
        if not dimensions or dimensions[1] == 0:
            return 0.0
        return dimensions[0] / dimensions[1]
        
    def _extract_color_histogram(self, image_data: bytes) -> dict[str, int]:
        """Extract color histogram."""
        # Mock implementation
        return {"red": 100, "green": 120, "blue": 80}
        
    def _calculate_edge_density(self, image_data: bytes) -> float:
        """Calculate edge density."""
        # Mock implementation
        return 0.3
        
    def _calculate_brightness(self, image_data: bytes) -> float:
        """Calculate image brightness."""
        # Mock implementation
        return 0.6
        
    def _calculate_contrast(self, image_data: bytes) -> float:
        """Calculate image contrast."""
        # Mock implementation
        return 0.5
        
    async def _generate_image_embeddings(self, image_data: bytes) -> list[float]:
        """Generate image embeddings."""
        # Mock embeddings
        hash_obj = hashlib.md5(image_data)
        hash_hex = hash_obj.hexdigest()
        
        embeddings = []
        for i in range(0, len(hash_hex), 2):
            byte_pair = hash_hex[i:i+2]
            embeddings.append(int(byte_pair, 16) / 255.0)
            
        return embeddings[:256]  # Return 256-dimensional embeddings
        
    async def _classify_image(self, image_data: bytes) -> dict[str, float]:
        """Classify image content."""
        # Mock classification
        return {
            "person": 0.3,
            "object": 0.4,
            "scene": 0.2,
            "text": 0.1,
        }
        
    async def _detect_objects(self, image_data: bytes) -> list[dict[str, Any]]:
        """Detect objects in image."""
        # Mock object detection
        return [
            {"type": "person", "confidence": 0.8, "bbox": [10, 10, 100, 100]},
            {"type": "car", "confidence": 0.6, "bbox": [200, 150, 300, 200]},
        ]
        
    async def _classify_scene(self, image_data: bytes) -> list[str]:
        """Classify scene type."""
        # Mock scene classification
        return ["outdoor", "urban", "daylight"]
        
    async def _extract_text_from_image(self, image_data: bytes) -> str:
        """Extract text from image using OCR."""
        # Mock OCR
        return "Sample extracted text from image"
        
    async def _detect_faces(self, image_data: bytes) -> list[dict[str, Any]]:
        """Detect faces in image."""
        # Mock face detection
        return [
            {"bbox": [50, 50, 100, 100], "confidence": 0.9},
        ]
        
    def _calculate_image_quality_score(self, features: dict[str, Any]) -> float:
        """Calculate image quality score."""
        score = 0.0
        
        # Resolution score
        if features["dimensions"]:
            width, height = features["dimensions"]
            if width >= 1920 and height >= 1080:
                score += 0.4
            elif width >= 1280 and height >= 720:
                score += 0.3
            elif width >= 640 and height >= 480:
                score += 0.2
                
        # Aspect ratio score
        aspect_ratio = features["aspect_ratio"]
        if 0.5 <= aspect_ratio <= 2.0:
            score += 0.2
            
        # Brightness score
        brightness = features["brightness"]
        if 0.3 <= brightness <= 0.7:
            score += 0.2
            
        # Contrast score
        contrast = features["contrast"]
        if 0.2 <= contrast <= 0.8:
            score += 0.2
            
        return min(1.0, score)


class AudioProcessor:
    """Audio processing and analysis."""
    
    def __init__(self, model_client):
        self.model_client = model_client
        self.processor_id = "audio_processor_v1"
        
    async def process(self, content: MediaContent) -> ProcessingResult:
        """Process audio content."""
        start_time = time.time()
        
        try:
            content.processing_status = ProcessingStatus.PROCESSING
            
            # Extract audio features
            features = {
                "format": content.mime_type,
                "size": content.size_bytes,
                "duration": content.duration,
                "sample_rate": 44100,  # Mock
                "channels": 2,  # Mock
                "bitrate": 128000,  # Mock
                "loudness": self._calculate_loudness(content.raw_data),
                "spectral_centroid": self._calculate_spectral_centroid(content.raw_data),
                "zero_crossing_rate": self._calculate_zero_crossing_rate(content.raw_data),
            }
            
            # Generate embeddings
            embeddings = await self._generate_audio_embeddings(content.raw_data)
            
            # Classify content
            classifications = await self._classify_audio(content.raw_data)
            
            # Extract structured data
            structured_data = {
                "transcription": await self._transcribe_audio(content.raw_data),
                "speaker_count": await self._detect_speakers(content.raw_data),
                "language": await self._detect_audio_language(content.raw_data),
                "emotions": await self._detect_emotions(content.raw_data),
                "music_genre": await self._classify_music_genre(content.raw_data),
            }
            
            processing_time = time.time() - start_time
            
            result = ProcessingResult(
                content_id=content.content_id,
                modality=ModalityType.AUDIO,
                processor_id=self.processor_id,
                extracted_features=features,
                structured_data=structured_data,
                embeddings=embeddings,
                classifications=classifications,
                processing_time=processing_time,
                quality_score=self._calculate_audio_quality_score(features),
                confidence=0.6,
                processor_version="1.0",
            )
            
            content.processed_data = result.to_dict()
            content.processing_status = ProcessingStatus.COMPLETED
            content.processed_at = time.time()
            
            return result
            
        except Exception as exc:
            content.processing_status = ProcessingStatus.FAILED
            
            return ProcessingResult(
                content_id=content.content_id,
                modality=ModalityType.AUDIO,
                processor_id=self.processor_id,
                processing_time=time.time() - start_time,
                errors=[str(exc)],
                confidence=0.0,
            )
            
    def _calculate_loudness(self, audio_data: bytes) -> float:
        """Calculate audio loudness."""
        # Mock implementation
        return 0.7
        
    def _calculate_spectral_centroid(self, audio_data: bytes) -> float:
        """Calculate spectral centroid."""
        # Mock implementation
        return 0.5
        
    def _calculate_zero_crossing_rate(self, audio_data: bytes) -> float:
        """Calculate zero crossing rate."""
        # Mock implementation
        return 0.1
        
    async def _generate_audio_embeddings(self, audio_data: bytes) -> list[float]:
        """Generate audio embeddings."""
        # Mock embeddings
        hash_obj = hashlib.md5(audio_data)
        hash_hex = hash_obj.hexdigest()
        
        embeddings = []
        for i in range(0, len(hash_hex), 2):
            byte_pair = hash_hex[i:i+2]
            embeddings.append(int(byte_pair, 16) / 255.0)
            
        return embeddings[:128]  # Return 128-dimensional embeddings
        
    async def _classify_audio(self, audio_data: bytes) -> dict[str, float]:
        """Classify audio content."""
        # Mock classification
        return {
            "speech": 0.4,
            "music": 0.3,
            "noise": 0.2,
            "silence": 0.1,
        }
        
    async def _transcribe_audio(self, audio_data: bytes) -> str:
        """Transcribe audio to text."""
        # Mock transcription
        return "This is a sample transcription of the audio content."
        
    async def _detect_speakers(self, audio_data: bytes) -> int:
        """Detect number of speakers."""
        # Mock speaker detection
        return 2
        
    async def _detect_audio_language(self, audio_data: bytes) -> str:
        """Detect spoken language."""
        # Mock language detection
        return "en"
        
    async def _detect_emotions(self, audio_data: bytes) -> dict[str, float]:
        """Detect emotions in speech."""
        # Mock emotion detection
        return {
            "happy": 0.3,
            "sad": 0.1,
            "angry": 0.1,
            "neutral": 0.5,
        }
        
    async def _classify_music_genre(self, audio_data: bytes) -> str:
        """Classify music genre."""
        # Mock genre classification
        return "pop"
        
    def _calculate_audio_quality_score(self, features: dict[str, Any]) -> float:
        """Calculate audio quality score."""
        score = 0.0
        
        # Duration score
        duration = features["duration"]
        if duration and 1.0 <= duration <= 300.0:  # 1 second to 5 minutes
            score += 0.3
            
        # Loudness score
        loudness = features["loudness"]
        if 0.1 <= loudness <= 0.9:
            score += 0.3
            
        # Sample rate score
        if features["sample_rate"] >= 44100:
            score += 0.2
            
        # Bitrate score
        if features["bitrate"] >= 128000:
            score += 0.2
            
        return min(1.0, score)


class VideoProcessor:
    """Video processing and analysis."""
    
    def __init__(self, model_client):
        self.model_client = model_client
        self.processor_id = "video_processor_v1"
        
    async def process(self, content: MediaContent) -> ProcessingResult:
        """Process video content."""
        start_time = time.time()
        
        try:
            content.processing_status = ProcessingStatus.PROCESSING
            
            # Extract video features
            features = {
                "format": content.mime_type,
                "size": content.size_bytes,
                "duration": content.duration,
                "dimensions": content.dimensions,
                "frame_rate": 30.0,  # Mock
                "bitrate": 2000000,  # Mock
                "codec": "h264",  # Mock
                "aspect_ratio": self._calculate_aspect_ratio(content.dimensions),
            }
            
            # Generate embeddings
            embeddings = await self._generate_video_embeddings(content.raw_data)
            
            # Classify content
            classifications = await self._classify_video(content.raw_data)
            
            # Extract structured data
            structured_data = {
                "scenes": await self._detect_scenes(content.raw_data),
                "objects": await self._track_objects(content.raw_data),
                "actions": await self._detect_actions(content.raw_data),
                "transcript": await self._transcribe_video(content.raw_data),
                "keyframes": await self._extract_keyframes(content.raw_data),
            }
            
            processing_time = time.time() - start_time
            
            result = ProcessingResult(
                content_id=content.content_id,
                modality=ModalityType.VIDEO,
                processor_id=self.processor_id,
                extracted_features=features,
                structured_data=structured_data,
                embeddings=embeddings,
                classifications=classifications,
                processing_time=processing_time,
                quality_score=self._calculate_video_quality_score(features),
                confidence=0.5,
                processor_version="1.0",
            )
            
            content.processed_data = result.to_dict()
            content.processing_status = ProcessingStatus.COMPLETED
            content.processed_at = time.time()
            
            return result
            
        except Exception as exc:
            content.processing_status = ProcessingStatus.FAILED
            
            return ProcessingResult(
                content_id=content.content_id,
                modality=ModalityType.VIDEO,
                processor_id=self.processor_id,
                processing_time=time.time() - start_time,
                errors=[str(exc)],
                confidence=0.0,
            )
            
    def _calculate_aspect_ratio(self, dimensions: tuple[int, int] | None) -> float:
        """Calculate aspect ratio."""
        if not dimensions or dimensions[1] == 0:
            return 0.0
        return dimensions[0] / dimensions[1]
        
    async def _generate_video_embeddings(self, video_data: bytes) -> list[float]:
        """Generate video embeddings."""
        # Mock embeddings
        hash_obj = hashlib.md5(video_data)
        hash_hex = hash_obj.hexdigest()
        
        embeddings = []
        for i in range(0, len(hash_hex), 2):
            byte_pair = hash_hex[i:i+2]
            embeddings.append(int(byte_pair, 16) / 255.0)
            
        return embeddings[:512]  # Return 512-dimensional embeddings
        
    async def _classify_video(self, video_data: bytes) -> dict[str, float]:
        """Classify video content."""
        # Mock classification
        return {
            "person": 0.4,
            "object": 0.3,
            "scene": 0.2,
            "action": 0.1,
        }
        
    async def _detect_scenes(self, video_data: bytes) -> list[dict[str, Any]]:
        """Detect scene changes."""
        # Mock scene detection
        return [
            {"timestamp": 0.0, "type": "intro", "confidence": 0.8},
            {"timestamp": 10.0, "type": "main_content", "confidence": 0.9},
            {"timestamp": 60.0, "type": "outro", "confidence": 0.7},
        ]
        
    async def _track_objects(self, video_data: bytes) -> list[dict[str, Any]]:
        """Track objects across frames."""
        # Mock object tracking
        return [
            {"type": "person", "track_id": 1, "confidence": 0.8},
            {"type": "car", "track_id": 2, "confidence": 0.6},
        ]
        
    async def _detect_actions(self, video_data: bytes) -> list[str]:
        """Detect actions in video."""
        # Mock action detection
        return ["walking", "talking", "sitting"]
        
    async def _transcribe_video(self, video_data: bytes) -> str:
        """Transcribe video audio."""
        # Mock transcription
        return "This is a sample transcription of the video content."
        
    async def _extract_keyframes(self, video_data: bytes) -> list[dict[str, Any]]:
        """Extract keyframes."""
        # Mock keyframe extraction
        return [
            {"timestamp": 0.0, "frame_id": 1},
            {"timestamp": 15.0, "frame_id": 450},
            {"timestamp": 30.0, "frame_id": 900},
        ]
        
    def _calculate_video_quality_score(self, features: dict[str, Any]) -> float:
        """Calculate video quality score."""
        score = 0.0
        
        # Resolution score
        if features["dimensions"]:
            width, height = features["dimensions"]
            if width >= 1920 and height >= 1080:
                score += 0.3
            elif width >= 1280 and height >= 720:
                score += 0.2
                
        # Frame rate score
        if features["frame_rate"] >= 30:
            score += 0.2
            
        # Bitrate score
        if features["bitrate"] >= 2000000:
            score += 0.2
            
        # Duration score
        duration = features["duration"]
        if duration and 5.0 <= duration <= 600.0:  # 5 seconds to 10 minutes
            score += 0.3
            
        return min(1.0, score)


class MultiModalProcessor:
    """Unified multi-modal processing system."""
    
    def __init__(self, model_client, redis_url: str = "redis://localhost:6379"):
        self.model_client = model_client
        self.redis_url = redis_url
        self._redis: redis.Redis | None = None
        
        # Modality processors
        self.processors = {
            ModalityType.TEXT: TextProcessor(model_client),
            ModalityType.IMAGE: ImageProcessor(model_client),
            ModalityType.AUDIO: AudioProcessor(model_client),
            ModalityType.VIDEO: VideoProcessor(model_client),
        }
        
        # Processing queue
        self.processing_queue: asyncio.Queue = asyncio.Queue()
        self.processing_task: asyncio.Task | None = None
        
        # Results storage
        self.results: dict[str, ProcessingResult] = {}
        self.contents: dict[str, MediaContent] = {}
        
    async def initialize(self) -> None:
        """Initialize the multi-modal processor."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Start processing task
        self.processing_task = asyncio.create_task(self._processing_loop())
        
        logger.info("MultiModalProcessor initialized")
        
    async def shutdown(self) -> None:
        """Shutdown the multi-modal processor."""
        if self.processing_task:
            self.processing_task.cancel()
            
        if self._redis:
            await self._redis.close()
            
        logger.info("MultiModalProcessor shutdown")
        
    async def _processing_loop(self) -> None:
        """Background processing loop."""
        while True:
            try:
                content = await self.processing_queue.get()
                await self._process_content(content)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Processing loop error: %s", exc)
                await asyncio.sleep(1.0)
                
    async def _process_content(self, content: MediaContent) -> None:
        """Process content with appropriate processor."""
        processor = self.processors.get(content.modality)
        if not processor:
            logger.error("No processor for modality: %s", content.modality)
            return
            
        try:
            result = await processor.process(content)
            self.results[result.result_id] = result
            self.contents[content.content_id] = content
            
            # Store in Redis
            if self._redis:
                await self._store_result(result)
                await self._store_content(content)
                
        except Exception as exc:
            logger.error("Content processing failed: %s", exc)
            
    async def _store_result(self, result: ProcessingResult) -> None:
        """Store processing result in Redis."""
        key = f"multimodal:result:{result.result_id}"
        await self._redis.setex(key, 86400, json.dumps(result.to_dict()))  # 24 hours
        
    async def _store_content(self, content: MediaContent) -> None:
        """Store content in Redis."""
        key = f"multimodal:content:{content.content_id}"
        await self._redis.setex(key, 86400, json.dumps(content.to_dict()))  # 24 hours
        
    async def submit_content(
        self,
        raw_data: str | bytes,
        modality: ModalityType,
        mime_type: str = "",
        metadata: dict[str, Any] | None = None
    ) -> str:
        """Submit content for processing."""
        content = MediaContent(
            modality=modality,
            raw_data=raw_data,
            mime_type=mime_type,
            size_bytes=len(raw_data) if isinstance(raw_data, bytes) else len(raw_data.encode()),
            metadata=metadata or {},
        )
        
        await self.processing_queue.put(content)
        
        return content.content_id
        
    async def get_result(self, result_id: str) -> ProcessingResult | None:
        """Get processing result."""
        if result_id in self.results:
            return self.results[result_id]
            
        # Try Redis
        if self._redis:
            key = f"multimodal:result:{result_id}"
            data = await self._redis.get(key)
            if data:
                result_dict = json.loads(data)
                result = ProcessingResult(
                    result_id=result_dict["result_id"],
                    content_id=result_dict["content_id"],
                    modality=ModalityType(result_dict["modality"]),
                    processor_id=result_dict["processor_id"],
                    extracted_features=result_dict["extracted_features"],
                    structured_data=result_dict["structured_data"],
                    embeddings=result_dict["embeddings"],
                    classifications=result_dict["classifications"],
                    processing_time=result_dict["processing_time"],
                    quality_score=result_dict["quality_score"],
                    confidence=result_dict["confidence"],
                    errors=result_dict["errors"],
                    warnings=result_dict["warnings"],
                    processor_version=result_dict["processor_version"],
                    processing_parameters=result_dict["processing_parameters"],
                    timestamp=result_dict["timestamp"],
                )
                self.results[result_id] = result
                return result
                
        return None
        
    async def fuse_modalities(
        self,
        content_ids: list[str],
        strategy: FusionStrategy = FusionStrategy.LATE_FUSION
    ) -> FusionResult:
        """Fuse multiple modalities."""
        start_time = time.time()
        
        # Get all results
        results = []
        for content_id in content_ids:
            # Find result for this content
            for result in self.results.values():
                if result.content_id == content_id:
                    results.append(result)
                    break
                    
        if not results:
            raise ValueError("No results found for content IDs")
            
        # Perform fusion based on strategy
        if strategy == FusionStrategy.LATE_FUSION:
            fusion_result = await self._late_fusion(results, strategy)
        elif strategy == FusionStrategy.EARLY_FUSION:
            fusion_result = await self._early_fusion(results, strategy)
        elif strategy == FusionStrategy.ATTENTION_FUSION:
            fusion_result = await self._attention_fusion(results, strategy)
        else:
            fusion_result = await self._hybrid_fusion(results, strategy)
            
        fusion_result.processing_time = time.time() - start_time
        
        return fusion_result
        
    async def _late_fusion(self, results: list[ProcessingResult], strategy: FusionStrategy) -> FusionResult:
        """Late fusion strategy."""
        # Combine features from all results
        unified_features = {}
        unified_embeddings = []
        
        for result in results:
            # Add modality-specific features
            for key, value in result.extracted_features.items():
                unified_features[f"{result.modality.value}_{key}"] = value
                
            # Concatenate embeddings
            if result.embeddings:
                unified_embeddings.extend(result.embeddings)
                
        # Calculate quality metrics
        avg_quality = sum(r.quality_score for r in results) / len(results)
        avg_confidence = sum(r.confidence for r in results) / len(results)
        
        # Generate cross-modal insights
        insights = []
        if len(results) > 1:
            insights.append(f"Combined {len(results)} modalities")
            insights.append(f"Average quality: {avg_quality:.2f}")
            
        return FusionResult(
            content_ids=[r.content_id for r in results],
            strategy=strategy,
            unified_features=unified_features,
            unified_embeddings=unified_embeddings,
            cross_modal_insights=insights,
            fusion_quality=avg_quality,
            consistency_score=avg_confidence,
            completeness_score=len(results) / 4.0,  # 4 modalities total
        )
        
    async def _early_fusion(self, results: list[ProcessingResult], strategy: FusionStrategy) -> FusionResult:
        """Early fusion strategy."""
        # Simple implementation - similar to late fusion
        return await self._late_fusion(results, strategy)
        
    async def _attention_fusion(self, results: list[ProcessingResult], strategy: FusionStrategy) -> FusionResult:
        """Attention-based fusion strategy."""
        # Weight results by confidence
        total_confidence = sum(r.confidence for r in results)
        
        unified_features = {}
        unified_embeddings = []
        
        for result in results:
            weight = result.confidence / total_confidence if total_confidence > 0 else 0.25
            
            # Weight features
            for key, value in result.extracted_features.items():
                if isinstance(value, (int, float)):
                    unified_features[f"{result.modality.value}_{key}"] = value * weight
                    
            # Weight embeddings
            if result.embeddings:
                weighted_embeddings = [e * weight for e in result.embeddings]
                if not unified_embeddings:
                    unified_embeddings = weighted_embeddings
                else:
                    unified_embeddings = [
                        ue + we for ue, we in zip(unified_embeddings, weighted_embeddings)
                    ]
                    
        return FusionResult(
            content_ids=[r.content_id for r in results],
            strategy=strategy,
            unified_features=unified_features,
            unified_embeddings=unified_embeddings,
            cross_modal_insights=["Attention-based fusion applied"],
            fusion_quality=sum(r.quality_score * r.confidence for r in results) / total_confidence,
            consistency_score=0.8,
            completeness_score=len(results) / 4.0,
        )
        
    async def _hybrid_fusion(self, results: list[ProcessingResult], strategy: FusionStrategy) -> FusionResult:
        """Hybrid fusion strategy."""
        # Combine early and late fusion
        early_result = await self._early_fusion(results, FusionStrategy.EARLY_FUSION)
        late_result = await self._late_fusion(results, FusionStrategy.LATE_FUSION)
        
        # Average the results
        return FusionResult(
            content_ids=[r.content_id for r in results],
            strategy=strategy,
            unified_features=early_result.unified_features,
            unified_embeddings=late_result.unified_embeddings,
            cross_modal_insights=early_result.cross_modal_insights + late_result.cross_modal_insights,
            fusion_quality=(early_result.fusion_quality + late_result.fusion_quality) / 2,
            consistency_score=(early_result.consistency_score + late_result.consistency_score) / 2,
            completeness_score=(early_result.completeness_score + late_result.completeness_score) / 2,
        )
        
    def get_processing_stats(self) -> dict[str, Any]:
        """Get processing statistics."""
        return {
            "total_contents": len(self.contents),
            "total_results": len(self.results),
            "processing_queue_size": self.processing_queue.qsize(),
            "modality_counts": {
                modality.value: sum(
                    1 for r in self.results.values()
                    if r.modality == modality
                )
                for modality in ModalityType
            },
            "average_quality": (
                sum(r.quality_score for r in self.results.values()) / len(self.results)
                if self.results else 0.0
            ),
            "average_confidence": (
                sum(r.confidence for r in self.results.values()) / len(self.results)
                if self.results else 0.0
            ),
        }


# Global multi-modal processor instance
multimodal_processor: MultiModalProcessor | None = None