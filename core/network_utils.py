import subprocess
import logging
import os
import time

logger = logging.getLogger(__name__)

def kill_process_on_port(port: int) -> bool:
    """
    지정된 포트를 사용 중인 프로세스를 찾아 종료합니다. (Windows 전용)
    
    Args:
        port: 종료할 포트 번호
        
    Returns:
        bool: 프로세스 종료 성공 여부 (또는 해당 포트를 사용하는 프로세스가 없는 경우 True)
    """
    try:
        # 1. 포트를 사용 중인 PID 찾기 (LISTENING 상태)
        # netstat -ano | findstr LISTENING | findstr :<port>
        cmd = f'netstat -ano | findstr LISTENING | findstr :{port}'
        try:
            output = subprocess.check_output(cmd, shell=True).decode('utf-8')
        except subprocess.CalledProcessError:
            # findstr이 아무것도 못 찾으면 발생 (해당 포트를 사용하는 프로세스 없음)
            return True

        lines = output.strip().split('\n')
        pids = set()
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 5:
                # 마지막 파트가 PID
                pid = parts[-1]
                # 정확한 포트 매칭 확인 (예: 80000과 8000 구분)
                address = parts[1]
                if f":{port}" in address:
                    pids.add(pid)

        if not pids:
            return True

        # 2. 프로세스 종료
        # 현재 프로세스의 PID를 가져와서 자신을 죽이지 않도록 함
        current_pid = str(os.getpid())
        
        success = True
        for pid in pids:
            if pid == current_pid:
                logger.warning(f"포트 {port}를 현재 프로세스(PID: {pid})가 사용 중입니다. 건너뜁니다.")
                continue
                
            logger.info(f"포트 {port}를 사용 중인 프로세스(PID: {pid})를 종료합니다...")
            try:
                # /F: 강제 종료, /T: 자식 프로세스까지 종료
                subprocess.run(['taskkill', '/F', '/T', '/PID', pid], check=True, capture_output=True)
                logger.info(f"PID {pid} 종료 완료.")
                # 소켓이 해제될 때까지 아주 잠시 대기
                time.sleep(0.5)
            except subprocess.CalledProcessError as e:
                logger.error(f"PID {pid} 종료 실패: {e.stderr.decode('cp949', errors='ignore')}")
                success = False
        
        return success

    except Exception as e:
        logger.error(f"포트 {port} 프로세스 종료 시도 중 오류 발생: {e}")
        return False
