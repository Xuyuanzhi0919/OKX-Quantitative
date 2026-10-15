"""
API配置管理端点
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from loguru import logger

from app.core.database import get_db
from app.api.deps import ensure_default_user
from app.models.api_config import APIConfig
from app.services.exchange.okx import OKXExchange

router = APIRouter()


class APIConfigCreate(BaseModel):
    """创建API配置请求"""

    name: str = Field(..., description="配置名称")
    exchange: str = Field(default="OKX", description="交易所名称")
    api_key: str = Field(..., description="API Key")
    secret_key: str = Field(..., description="Secret Key")
    passphrase: str = Field(..., description="Passphrase")
    is_simulated: bool = Field(default=False, description="是否模拟盘")
    proxy: Optional[str] = Field(None, description="代理地址")


class APIConfigUpdate(BaseModel):
    """更新API配置请求"""

    name: Optional[str] = None
    api_key: Optional[str] = None
    secret_key: Optional[str] = None
    passphrase: Optional[str] = None
    is_simulated: Optional[bool] = None
    proxy: Optional[str] = None


class APIConfigResponse(BaseModel):
    """API配置响应"""

    id: int
    name: str
    exchange: str
    api_key: str  # 仅显示前8位
    is_simulated: bool
    is_active: bool
    is_valid: bool
    proxy: Optional[str]
    last_verified_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


def get_management_user_id(db: Session = Depends(get_db)) -> int:
    """Management UI currently runs without login; use the legacy local user."""
    return ensure_default_user(db)


@router.get("/list", response_model=List[APIConfigResponse])
async def list_configs(
    user_id: int = Depends(get_management_user_id), db: Session = Depends(get_db)
):
    """
    获取用户的所有API配置列表
    """
    try:
        configs = (
            db.query(APIConfig)
            .filter(APIConfig.user_id == user_id)
            .order_by(APIConfig.is_active.desc(), APIConfig.created_at.desc())
            .all()
        )

        # 隐藏敏感信息
        result = []
        for config in configs:
            config_dict = {
                "id": config.id,
                "name": config.name,
                "exchange": config.exchange,
                "api_key": (
                    config.api_key[:8] + "..."
                    if len(config.api_key) > 8
                    else config.api_key
                ),
                "is_simulated": config.is_simulated,
                "is_active": config.is_active,
                "is_valid": config.is_valid,
                "proxy": config.proxy,
                "last_verified_at": config.last_verified_at,
                "error_message": config.error_message,
                "created_at": config.created_at,
                "updated_at": config.updated_at,
            }
            result.append(config_dict)

        logger.info(f"用户 {user_id} 共有 {len(result)} 个API配置")
        return result

    except Exception as e:
        logger.error(f"获取API配置列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create", response_model=APIConfigResponse)
async def create_config(
    request: APIConfigCreate,
    user_id: int = Depends(get_management_user_id),
    db: Session = Depends(get_db),
):
    """
    创建新的API配置
    """
    try:
        # 验证API配置是否有效
        is_valid, error_msg = await verify_api_config(
            api_key=request.api_key,
            secret_key=request.secret_key,
            passphrase=request.passphrase,
            is_simulated=request.is_simulated,
            proxy=request.proxy,
        )

        # 创建配置
        config = APIConfig(
            user_id=user_id,
            name=request.name,
            exchange=request.exchange,
            api_key=request.api_key,
            secret_key=request.secret_key,
            passphrase=request.passphrase,
            is_simulated=request.is_simulated,
            proxy=request.proxy,
            is_valid=is_valid,
            error_message=error_msg,
            last_verified_at=datetime.utcnow() if is_valid else None,
        )

        db.add(config)
        db.commit()
        db.refresh(config)

        logger.info(f"用户 {user_id} 创建API配置: {config.name} (ID: {config.id})")

        return APIConfigResponse(
            id=config.id,
            name=config.name,
            exchange=config.exchange,
            api_key=config.api_key[:8] + "...",
            is_simulated=config.is_simulated,
            is_active=config.is_active,
            is_valid=config.is_valid,
            proxy=config.proxy,
            last_verified_at=config.last_verified_at,
            error_message=config.error_message,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

    except Exception as e:
        logger.error(f"创建API配置失败: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{config_id}/activate")
async def activate_config(
    config_id: int,
    user_id: int = Depends(get_management_user_id),
    db: Session = Depends(get_db),
):
    """
    激活指定的API配置 (切换到该配置)
    """
    try:
        # 查找配置
        config = (
            db.query(APIConfig)
            .filter(APIConfig.id == config_id, APIConfig.user_id == user_id)
            .first()
        )

        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")

        if not config.is_valid:
            raise HTTPException(
                status_code=400, detail=f"配置无效: {config.error_message}"
            )

        # 取消其他配置的激活状态
        db.query(APIConfig).filter(
            APIConfig.user_id == user_id, APIConfig.is_active == True
        ).update({"is_active": False})

        # 激活当前配置
        config.is_active = True
        db.commit()

        logger.info(f"用户 {user_id} 激活API配置: {config.name} (ID: {config_id})")

        return {
            "code": 0,
            "msg": f"已切换到 {config.name} ({'模拟盘' if config.is_simulated else '实盘'})",
            "data": {
                "id": config.id,
                "name": config.name,
                "is_simulated": config.is_simulated,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"激活API配置失败: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active")
async def get_active_config(
    user_id: int = Depends(get_management_user_id), db: Session = Depends(get_db)
):
    """
    获取当前激活的API配置
    """
    try:
        config = (
            db.query(APIConfig)
            .filter(APIConfig.user_id == user_id, APIConfig.is_active == True)
            .first()
        )

        if not config:
            return {"code": 0, "msg": "未设置API配置", "data": None}

        return {
            "code": 0,
            "msg": "success",
            "data": {
                "id": config.id,
                "name": config.name,
                "exchange": config.exchange,
                "is_simulated": config.is_simulated,
                "is_valid": config.is_valid,
                "proxy": config.proxy,
            },
        }

    except Exception as e:
        logger.error(f"获取激活配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{config_id}")
async def delete_config(
    config_id: int,
    user_id: int = Depends(get_management_user_id),
    db: Session = Depends(get_db),
):
    """
    删除API配置
    """
    try:
        config = (
            db.query(APIConfig)
            .filter(APIConfig.id == config_id, APIConfig.user_id == user_id)
            .first()
        )

        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")

        if config.is_active:
            raise HTTPException(status_code=400, detail="无法删除当前激活的配置")

        db.delete(config)
        db.commit()

        logger.info(f"用户 {user_id} 删除API配置: {config.name} (ID: {config_id})")

        return {"code": 0, "msg": "删除成功", "data": None}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除API配置失败: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{config_id}/verify")
async def verify_config(
    config_id: int,
    user_id: int = Depends(get_management_user_id),
    db: Session = Depends(get_db),
):
    """
    验证API配置是否有效
    """
    try:
        config = (
            db.query(APIConfig)
            .filter(APIConfig.id == config_id, APIConfig.user_id == user_id)
            .first()
        )

        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")

        # 验证配置
        is_valid, error_msg = await verify_api_config(
            api_key=config.api_key,
            secret_key=config.secret_key,
            passphrase=config.passphrase,
            is_simulated=config.is_simulated,
            proxy=config.proxy,
        )

        # 更新验证结果
        config.is_valid = is_valid
        config.error_message = error_msg
        config.last_verified_at = datetime.utcnow()
        db.commit()

        logger.info(f"验证API配置 {config.name}: {'有效' if is_valid else '无效'}")

        return {
            "code": 0,
            "msg": "验证完成",
            "data": {"is_valid": is_valid, "error_message": error_msg},
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证API配置失败: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


async def verify_api_config(
    api_key: str,
    secret_key: str,
    passphrase: str,
    is_simulated: bool,
    proxy: Optional[str],
) -> tuple[bool, Optional[str]]:
    """
    验证API配置是否有效

    Returns:
        (is_valid, error_message)
    """
    exchange = OKXExchange(
        api_key=api_key,
        secret_key=secret_key,
        passphrase=passphrase,
        simulated=is_simulated,
        proxy=proxy,
    )

    try:
        # 尝试获取账户余额来验证
        await exchange.get_balance()

        return True, None

    except Exception as e:
        error_msg = str(e)
        logger.warning(f"API配置验证失败: {error_msg}")
        return False, error_msg
    finally:
        await exchange.close()
