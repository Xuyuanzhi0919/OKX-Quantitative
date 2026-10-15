"""
AI配置管理API端点
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.core.database import get_db
from app.api.deps import require_current_user_id
from app.models.ai_config import AIConfig

router = APIRouter()


class AIConfigCreate(BaseModel):
    name: str
    provider: str = "deepseek"
    api_key: str
    model: str = "deepseek-chat"


class AIConfigUpdate(BaseModel):
    name: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    is_active: Optional[bool] = None


class AIConfigResponse(BaseModel):
    id: int
    name: str
    provider: str
    model: str
    is_active: bool
    created_at: str
    updated_at: Optional[str] = None


get_current_user_id = require_current_user_id


@router.get("/list", response_model=list[AIConfigResponse])
async def list_configs(
    user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)
):
    """获取AI配置列表"""
    configs = db.query(AIConfig).filter(AIConfig.user_id == user_id).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "provider": c.provider,
            "model": c.model,
            "is_active": c.is_active,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in configs
    ]


@router.post("/create", response_model=AIConfigResponse)
async def create_config(
    config: AIConfigCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """创建AI配置"""
    try:
        # 如果新配置设置为激活，先将其他配置设为非激活
        if hasattr(config, "is_active") and config.is_active:
            db.query(AIConfig).filter(AIConfig.user_id == user_id).update(
                {"is_active": False}
            )

        new_config = AIConfig(
            user_id=user_id,
            name=config.name,
            provider=config.provider,
            api_key=config.api_key,
            model=config.model,
            is_active=False,  # 创建后默认不激活
        )

        db.add(new_config)
        db.commit()
        db.refresh(new_config)

        return {
            "id": new_config.id,
            "name": new_config.name,
            "provider": new_config.provider,
            "model": new_config.model,
            "is_active": new_config.is_active,
            "created_at": (
                new_config.created_at.isoformat() if new_config.created_at else None
            ),
            "updated_at": (
                new_config.updated_at.isoformat() if new_config.updated_at else None
            ),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.put("/update/{config_id}")
async def update_config(
    config_id: int,
    config: AIConfigUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """更新AI配置"""
    try:
        db_config = (
            db.query(AIConfig)
            .filter(AIConfig.id == config_id, AIConfig.user_id == user_id)
            .first()
        )

        if not db_config:
            raise HTTPException(status_code=404, detail="配置不存在")

        # 如果设置为激活，先将其他配置设为非激活
        if config.is_active and not db_config.is_active:
            db.query(AIConfig).filter(AIConfig.user_id == user_id).update(
                {"is_active": False}
            )

        # 更新字段
        if config.name is not None:
            db_config.name = config.name
        if config.api_key is not None:
            db_config.api_key = config.api_key
        if config.model is not None:
            db_config.model = config.model
        if config.is_active is not None:
            db_config.is_active = config.is_active

        db.commit()
        return {"message": "更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.delete("/delete/{config_id}")
async def delete_config(
    config_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """删除AI配置"""
    try:
        db_config = (
            db.query(AIConfig)
            .filter(AIConfig.id == config_id, AIConfig.user_id == user_id)
            .first()
        )

        if not db_config:
            raise HTTPException(status_code=404, detail="配置不存在")

        db.delete(db_config)
        db.commit()
        return {"message": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.post("/activate/{config_id}")
async def activate_config(
    config_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """激活AI配置"""
    try:
        db_config = (
            db.query(AIConfig)
            .filter(AIConfig.id == config_id, AIConfig.user_id == user_id)
            .first()
        )

        if not db_config:
            raise HTTPException(status_code=404, detail="配置不存在")

        # 先将所有配置设为非激活
        db.query(AIConfig).filter(AIConfig.user_id == user_id).update(
            {"is_active": False}
        )

        # 激活当前配置
        db_config.is_active = True
        db.commit()

        return {"message": "激活成功"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"激活失败: {str(e)}")


@router.get("/active", response_model=AIConfigResponse)
async def get_active_config(
    user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)
):
    """获取当前激活的AI配置"""
    config = (
        db.query(AIConfig)
        .filter(AIConfig.user_id == user_id, AIConfig.is_active == True)
        .first()
    )

    if not config:
        raise HTTPException(status_code=404, detail="未设置AI配置")

    return {
        "id": config.id,
        "name": config.name,
        "provider": config.provider,
        "model": config.model,
        "is_active": config.is_active,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }
