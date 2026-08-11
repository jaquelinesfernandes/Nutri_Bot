from pydantic import BaseModel


class ZApiTextMessage(BaseModel):
    message: str = ""


class ZApiImageMessage(BaseModel):
    imageUrl: str = ""
    caption: str | None = None


class ZApiAudioMessage(BaseModel):
    audioUrl: str = ""


class ZApiWebhookPayload(BaseModel):
    instanceId: str = ""
    messageId: str = ""
    phone: str  # E.164 sem +
    fromMe: bool = False
    momment: int = 0
    type: str = "ReceivedCallback"
    chatName: str = ""
    senderName: str = ""
    text: ZApiTextMessage | None = None
    image: ZApiImageMessage | None = None
    audio: ZApiAudioMessage | None = None
