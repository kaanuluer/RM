import socket
import datetime

def start_printer_server(ip='0.0.0.0', port=9100, output_file='printed_output.txt'):
    """
    Listens for raw ESC/POS data on a socket and saves it to a file.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind((ip, port))
    except OSError as e:
        print(f"[!!!] CRITICAL ERROR: Could not bind to {ip}:{port}. Is another instance running? Error: {e}")
        return
        
    server.listen(1)
    
    try:
        hostname = socket.gethostname()
        actual_ip = socket.gethostbyname(hostname)
        print(f"[+] Virtual Printer Server started. Listening on {actual_ip}:{port} (or {ip}:{port})")
    except:
        print(f"[+] Virtual Printer Server started. Listening on {ip}:{port}")

    print(f"[+] Print jobs will be saved to '{output_file}'")

    while True:
        try:
            client, addr = server.accept()
            print(f"\n[+] Accepted connection from {addr}")
            
            data = b""
            client.settimeout(2.0)
            while True:
                try:
                    chunk = client.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                except socket.timeout:
                    break
            
            client.close()

            if data:
                with open(output_file, 'a', encoding='utf-8', errors='ignore') as f:
                    f.write("="*40 + "\n")
                    f.write(f"PRINT JOB RECEIVED AT: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("="*40 + "\n")
                    f.write(data.decode('cp437', errors='ignore'))
                    f.write("\n\n")

                print(f"[✓] Print job from {addr} saved to '{output_file}'")
            else:
                print(f"[-] Connection from {addr} closed with no data.")

        except Exception as e:
            print(f"[!] An error occurred during connection: {e}")

if __name__ == '__main__':
    start_printer_server()