from sqlalchemy import (
    Column, Integer, BigInteger, Text, DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Channel(Base):
    __tablename__ = "channels"

    id              = Column(Integer, primary_key=True)
    channel_id      = Column(Text, unique=True, nullable=False)  # YouTube channel ID
    name            = Column(Text, nullable=False)
    url             = Column(Text, nullable=False)
    last_scraped_at = Column(DateTime, nullable=True)

    videos = relationship("Video", back_populates="channel", cascade="all, delete")


class Video(Base):
    __tablename__ = "videos"

    id              = Column(Integer, primary_key=True)
    internal_id     = Column(Text, unique=True, nullable=False)   # e.g. BBCNews-25032026-143022-1
    yt_video_id     = Column(Text, unique=True, nullable=False)   # YouTube's official video ID
    channel_id      = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"))
    title           = Column(Text, nullable=False)
    description     = Column(Text)
    duration        = Column(Integer)                             # seconds
    view_count      = Column(BigInteger)
    like_count      = Column(BigInteger)
    thumbnail_url   = Column(Text)
    nas_file_path   = Column(Text)
    uploaded_at     = Column(DateTime)
    captions        = Column(JSONB)  # {"en": {"text": "...", "source": "auto|manual"}}
    status          = Column(Text, default="pending")            # pending|processing|processed|failed

    channel         = relationship("Channel", back_populates="videos")
    comments        = relationship("Comment", back_populates="video", cascade="all, delete")
    related_videos  = relationship("RelatedVideo", back_populates="video", cascade="all, delete")
    linked_articles = relationship("LinkedArticle", back_populates="video", cascade="all, delete")

class Comment(Base):
    __tablename__ = "comments"

    id           = Column(Integer, primary_key=True)
    video_id     = Column(Integer, ForeignKey("videos.id", ondelete="CASCADE"))
    comment_id   = Column(Text, unique=True, nullable=False)  # YouTube's comment ID
    author       = Column(Text)
    text         = Column(Text)
    like_count   = Column(BigInteger)
    reply_to     = Column(Text, nullable=True)                # parent comment_id if a reply
    published_at = Column(DateTime)

    video = relationship("Video", back_populates="comments")


class RelatedVideo(Base):
    __tablename__ = "related_videos"
    __table_args__ = (UniqueConstraint("video_id", "related_video_id", name="uq_related_videos_video_related"),)

    id               = Column(Integer, primary_key=True)
    video_id         = Column(Integer, ForeignKey("videos.id", ondelete="CASCADE"))
    related_video_id = Column(Text, nullable=False)           # YouTube video ID
    relation_type    = Column(Text)                           # suggested|end-screen|description-linked

    video = relationship("Video", back_populates="related_videos")


class LinkedArticle(Base):
    __tablename__ = "linked_articles"
    __table_args__ = (UniqueConstraint("video_id", "url", name="uq_linked_articles_video_url"),)

    id       = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="CASCADE"))
    url      = Column(Text, nullable=False)
    domain   = Column(Text)
    title    = Column(Text)
    found_in = Column(Text)                                   # description|pinned-comment

    video = relationship("Video", back_populates="linked_articles")
