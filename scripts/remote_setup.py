"""通过 SSH 在远程 Ubuntu 服务器上配置开发环境。"""
import os
import sys
import time

import paramiko

HOST = os.environ.get('DEPLOY_HOST', '43.134.95.83')
USER = os.environ.get('DEPLOY_USER', 'ubuntu')
PASSWORD = os.environ.get('DEPLOY_PASSWORD', '')
APP_DIR = '/home/ubuntu/stock-sentiment-app'
LOCAL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(client, cmd, timeout=3600):
    print(f'\n$ {cmd[:200]}...' if len(cmd) > 200 else f'\n$ {cmd}')
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True, timeout=timeout)
    if PASSWORD:
        stdin.write(PASSWORD + '\n')
        stdin.flush()
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out[-8000:] if len(out) > 8000 else out)
    if err.strip() and code != 0:
        print('STDERR:', err[-4000:] if len(err) > 4000 else err)
    if code != 0:
        raise RuntimeError(f'命令失败 exit={code}: {cmd[:120]}')
    return out


def sftp_upload(sftp, local_path, remote_path):
    print(f'上传 {local_path} -> {remote_path}')
    sftp.put(local_path, remote_path)


def main():
    if not PASSWORD:
        print('请设置环境变量 DEPLOY_PASSWORD', file=sys.stderr)
        sys.exit(1)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f'连接 {USER}@{HOST} ...')
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30)

    run(client, 'uname -a && lsb_release -a 2>/dev/null || cat /etc/os-release')
    run(client, f'mkdir -p {APP_DIR}/scripts')

    sftp = client.open_sftp()
    sftp_upload(sftp, os.path.join(LOCAL_ROOT, 'requirements.txt'), f'{APP_DIR}/requirements.txt')
    sftp_upload(sftp, os.path.join(LOCAL_ROOT, 'scripts', 'server_setup_env.sh'), f'{APP_DIR}/scripts/server_setup_env.sh')
    sftp.close()

    run(client, f'chmod +x {APP_DIR}/scripts/server_setup_env.sh')
    run(client, f"sed -i 's/\\r$//' {APP_DIR}/scripts/server_setup_env.sh")
    run(client, f'APP_DIR={APP_DIR} bash {APP_DIR}/scripts/server_setup_env.sh', timeout=7200)

    client.close()
    print('\n远程环境配置完成。')


if __name__ == '__main__':
    main()
