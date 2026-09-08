from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MediaReference:
    video_asset_id: str
    camera_id: str
    media_uri: str
