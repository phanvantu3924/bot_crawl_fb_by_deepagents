import os

# 1. Lỗi bảo mật: Lộ mật khẩu trong code
DB_PASSWORD = "secret_password_dont_tell_anyone"

# 2. Lỗi hiệu năng: Đệ quy vô tận hoặc xử lý cực chậm
def infinite_loop_logic(n):
    return infinite_loop_logic(n) # Sẽ gây tràn bộ nhớ (Stack Overflow)

# 3. Lỗi thực hành tốt: Catch mọi lỗi mà không xử lý (Nuốt lỗi)
def sensitive_process():
    try:
        # Giả sử có code quan trọng ở đây
        x = 1 / 0
    except Exception:
        pass # Rất nguy hiểm vì lỗi bị che giấu

# 4. Lỗi thực thi lệnh hệ thống (Command Injection)
def delete_file(filename):
    os.system(f"rm {filename}") # Người dùng có thể truyền vào "; rm -rf /"
