from pydantic import BaseModel


class TelegramUser(BaseModel):
    id: int
    is_bot: bool = False
    first_name: str = ""
    language_code: str = "pt-br"


class TelegramChat(BaseModel):
    id: int
    type: str = "private"


class TelegramPhotoSize(BaseModel):
    file_id: str
    file_unique_id: str
    width: int
    height: int
    file_size: int | None = None


class TelegramVoice(BaseModel):
    file_id: str
    file_unique_id: str
    duration: int
    mime_type: str = "audio/ogg"
    file_size: int | None = None


class TelegramMessage(BaseModel):
    message_id: int
    from_: TelegramUser | None = None
    chat: TelegramChat
    date: int
    text: str | None = None
    photo: list[TelegramPhotoSize] | None = None
    voice: TelegramVoice | None = None
    caption: str | None = None

    model_config = {"populate_by_name": True}

    @classmethod
    def model_validate(cls, obj, **kwargs):
        if isinstance(obj, dict) and "from" in obj:
            obj = {**obj, "from_": obj.pop("from")}
        return super().model_validate(obj, **kwargs)


class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramMessage | None = None
