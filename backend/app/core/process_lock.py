"""
进程锁管理模块 - 防止多实例启动

使用文件锁确保同一时间只有一个后端实例在运行
"""

import os
import sys
from pathlib import Path
from loguru import logger


# Windows平台检查
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class ProcessLock:
    """进程锁，使用文件锁实现单实例运行"""

    def __init__(self, lock_file: str = "app.lock"):
        """
        初始化进程锁

        Args:
            lock_file: 锁文件名（相对于backend目录）
        """
        # 锁文件路径（放在backend根目录）
        backend_dir = Path(__file__).parent.parent.parent
        self.lock_file = backend_dir / lock_file
        self.lock_fd = None

    def acquire(self) -> bool:
        """
        获取进程锁

        Returns:
            bool: 成功获取返回True，已有实例运行返回False
        """
        try:
            # 打开或创建锁文件
            self.lock_fd = open(self.lock_file, "w")

            # 根据平台使用不同的锁定机制
            if sys.platform == "win32":
                # Windows: 使用msvcrt
                msvcrt.locking(self.lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                # Unix/Linux: 使用fcntl
                fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # 写入当前进程ID
            self.lock_fd.write(f"{os.getpid()}\n")
            self.lock_fd.flush()

            logger.info(f"✅ 成功获取进程锁: {self.lock_file}")
            return True

        except (IOError, OSError) as e:
            if self.lock_fd:
                self.lock_fd.close()
                self.lock_fd = None

            # 读取锁文件中的进程ID
            try:
                with open(self.lock_file, "r") as f:
                    existing_pid = f.read().strip()
                logger.error(f"❌ 无法获取进程锁: 已有实例在运行 (PID: {existing_pid})")
            except:
                logger.error(f"❌ 无法获取进程锁: {e}")

            return False

    def release(self):
        """释放进程锁"""
        if self.lock_fd:
            try:
                # 根据平台使用不同的解锁机制
                if sys.platform == "win32":
                    # Windows: 使用msvcrt
                    msvcrt.locking(self.lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    # Unix/Linux: 使用fcntl
                    fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)

                self.lock_fd.close()
                self.lock_fd = None

                # 删除锁文件
                if self.lock_file.exists():
                    self.lock_file.unlink()

                logger.info(f"✅ 已释放进程锁: {self.lock_file}")
            except Exception as e:
                logger.error(f"❌ 释放进程锁失败: {e}")

    def __enter__(self):
        """上下文管理器入口"""
        if not self.acquire():
            logger.error("⛔ 检测到后端已在运行，请先停止现有实例")
            logger.error("提示：如果确认没有其他实例，请删除锁文件: app.lock")
            sys.exit(1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.release()

    def __del__(self):
        """析构时确保释放锁"""
        self.release()
