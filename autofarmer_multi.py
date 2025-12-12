# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

import pychrome
import json
import time
import subprocess
import socket
import os
import csv
import unicodedata
from pathlib import Path
from typing import Tuple
from datetime import datetime, timezone, timedelta

# Global variables
tab_ref = None
union_id:str|None = None
white_list_mode:bool = True
black_list_mode:bool = True
white_list_ids:list[str] = []
black_list_ids:list[str] = []
no_action_ids:list[str] = []
expel_inactive_members_time:int = 600
expel_inactive_members:bool = False
refresh_time:int = 30
rf_path:Path = os.path.dirname(os.path.abspath(__file__))
number_of_union_members:int = 0
player_id:str|None = None
cache_union_members_ids:dict[int:list[str, int]] = {}

    
# Inject WebSocket hook into the page
def inject_websocket_hook() -> None:
    try:
        # Inject WebSocket hook
        tab_ref.call_method("Runtime.evaluate", expression="""
        (() => {
            const originalSend = WebSocket.prototype.send;
            WebSocket.prototype.send = function(data) {
                window.__lastSocket__ = this;
                originalSend.call(this, data);
            };
        })();
        """)
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [*] WebSocket is ready.", end="\r")
    except Exception as e:
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [!] Error: {e}")


# Check applicant against white list and black list
def check_applicant(user_id:int) -> Tuple[str, str]:
    if white_list_mode and str(user_id) in white_list_ids:
        return "approve_member", "(Approved)"
    elif black_list_mode and str(user_id) in black_list_ids:
        return "reject_member", "(Rejected)"
    elif not white_list_mode and str(user_id) not in black_list_ids:
        return "approve_member", "(Approved)"
    else:
        return "", "(No Action)"

# Send payload to websocket
def sent_payload(payload:dict, return_status:str="") -> str:
    js_code = f"""
    (() => {{
      if (window.__lastSocket__) {{
        window.__lastSocket__.send('{payload}');
        return "{return_status}";
      }} else {{
        return "[!] Socket not ready. Please log in again.";
      }}
    }})();
    """
    result = tab_ref.call_method("Runtime.evaluate", expression=js_code)
    return result.get("result", {}).get("value")

# Format name string
def format_name(name:str) -> str:
    width = 0
    if name is None:
        return " " * 25
    try:
        for char in name:
            status = unicodedata.east_asian_width(char)
            if status == 'W' or status == 'F':
                width += 2  # Wide character
            else:
                width += 1  # Single-width character
    except:
        pass
    return f"{name}{' ' * (25 - width)}"

# Handle received WebSocket frames
def on_frame_received(requestId, timestamp, response: dict) -> None:
    global union_id
    global player_id
    global number_of_union_members
    global refresh_time
    global cache_union_members_ids
    
    applicants = None
    response_data = response["payloadData"]

    # Find player ID
    if "player:" in response_data:
        new_player_id = str(json.loads(response_data)[2].split(":")[1])
        if player_id != new_player_id:
            player_id = new_player_id
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [*] Detected new Player ID:", player_id)
    
    # Find union ID
    if "\"union\":{\"id\":" in response_data and "response" in response_data and "collected_items" not in response_data:
        new_union_id = str(json.loads(response_data)[4]["response"]["union"]["id"])
        if union_id != new_union_id:
            union_id = new_union_id
            sent_payload(json.dumps(["0","0","union:"+union_id,"phx_join",{"fake":"ChannelUnion"}]))
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [*] Detected new Union ID:", union_id)

    # Active check union applicants
    if "union_applicants" in response_data and "union:" in response_data:
        if "name" in response_data:
            applicants = json.loads(response_data)[4]["response"]["union_applicants"]
            refresh_time = max((60 / (1 + len(applicants))), 15)

    # Passive check for union applicants
    if "\"update_data\",{\"union_applicants" in response_data:
        applicants = json.loads(response_data)[4]["union_applicants"]

    # Passive check number of current union members
    if union_id:
        if "\"update_data\",{\"unions\":[{\"id\":" + union_id +",\"member_count\"" in response_data:
            number_of_union_members = int(json.loads(response_data)[4]["unions"][0]["member_count"])

    # Active check and cache union members
    if "union_contacts" in response_data and "union:" in response_data:
        union_members = json.loads(response_data)[4]["response"]["union_contacts"]
        number_of_union_members = len(union_members) - 1 
        # Cache union members for inactivity expulsion
        if number_of_union_members > 1 and expel_inactive_members:
            for member in union_members[2:]:
                member_id = member["friend_id"]
                member_name = member["name"]
                can_appoint = bool(member["can_appoint"])

                if can_appoint == False: continue
                if not member_id: continue

                if member_id not in cache_union_members_ids:
                    cache_union_members_ids[member_id] = [member_name, refresh_time]
                else:
                    cache_union_members_ids[member_id][1] += refresh_time
            
            temp_cache_union_members_ids = cache_union_members_ids.copy()
            for cache_union_member_id in cache_union_members_ids:
                if cache_union_member_id not in [member["friend_id"] for member in union_members]:
                    del temp_cache_union_members_ids[cache_union_member_id]
            cache_union_members_ids = temp_cache_union_members_ids

    # Return if no applicants found
    if applicants is None:
        return
        
    # Process each applicant
    for applicant in applicants:
        if str(applicant["id"]) in no_action_ids:
            continue

        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [*] Applicant : {format_name(applicant["name"])} id: {applicant["id"]} ", end=" ")
        if union_id:
            status, return_status = check_applicant(applicant["id"])
            match status: 
                case "approve_member":
                    if number_of_union_members < 9:
                        number_of_union_members += 1
                        payload:dict = json.dumps(["0", "0", "union:"+union_id, status, {"user_id": applicant["id"]}])
                        print(sent_payload(payload, return_status))
                    else:
                        print("(Union Full)")

                case "reject_member":
                    payload:dict = json.dumps(["0", "0", "union:"+union_id, status, {"user_id": applicant["id"]}])
                    print(sent_payload(payload, return_status))

                case _:
                    no_action_ids.append(str(applicant["id"]))
                    print(return_status)
                    continue
        else:
            print("(Union ID not detected)")
        time.sleep(0.5)

# Handle WebSocket creation, inject hook
def on_websocket_created(requestId, url, initiator) -> None:
    inject_websocket_hook()

# === MAIN ===
if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("="*80)
    print("RF AutoFarmer: v1.0")

    # Load white list
    if white_list_mode:
        print("[*] White list mode enabled.")
        try:
            with open("white_list.csv", "r") as f:
                reader = csv.reader(f, skipinitialspace=True)
                white_list_ids = [row[2].strip() for row in reader if len(row) > 1 and row[2].strip()][1:]
        except FileNotFoundError:
            with open("white_list.csv", "w") as f:
                f.write("Discord Name,Name,Id\n")
            print("[*] White list file created. Please add user IDs to white_list.csv.")

    # Load black list IDs
    if black_list_mode:
        print("[*] Black list mode enabled.")
        try:
            with open("black_list.csv", "r") as f:
                reader = csv.reader(f, skipinitialspace=True)
                black_list_ids = [row[1].strip() for row in reader if len(row) > 1 and row[1].strip()][1:]
        except FileNotFoundError:
            with open("black_list.csv", "w") as f:
                f.write("Name,Id\n")
            print("[*] Black list file created. Please add user IDs to black_list.csv.")
    
    # Connect to Chrome with remote debugging
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        for port in range(9221, 9231):
            if (s.connect_ex(("127.0.0.1", port)) != 0):
                print("[*] Launching Chrome...", end="\r")
                subprocess.Popen(rf'"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port={str(port)} --user-data-dir="C:\ChromeDebugProfile{str(port) if port != 9222 else ""}"')
                time.sleep(2)
                browser = pychrome.Browser(url=f"http://127.0.0.1:{str(port)}")
                break
            if port == 9230:
                raise Exception("All ports from 9221 to 9230 are in use.")
            
    time.sleep(0.5)
    tabs = browser.list_tab()
    tab = tabs[0]
    tab.start()
    tab_ref = tab

    # Enable required domains
    tab.call_method("Page.enable")
    tab.call_method("Runtime.enable")
    tab.call_method("Network.enable")
    
    # Check current URL
    try:
        nav_history = tab.call_method("Page.getNavigationHistory")
        current_url = nav_history["entries"][nav_history["currentIndex"]]["url"]
        if "2.28/assets/index.html" not in current_url:
            print("[*] Navigating to target URL...", end="\r")
            tab.call_method("Page.navigate", url=rf"{rf_path}/2.28/assets/index.html#/users/log_in", _timeout=5)
            print(rf"[*] URL: {rf_path}\2.28\assets\index.html")
            time.sleep(2)
        else:
            print(f"[*] URL: {current_url}")
    except Exception as e:
        print(f"Error retrieving URL: {e}")

    tab.call_method("WebAudio.disable")
    tab.call_method("Animation.disable")

    # Set listeners
    tab.set_listener("Network.webSocketFrameReceived", on_frame_received)
    tab.set_listener("Network.webSocketCreated", on_websocket_created)
    
    print("="*80)

    # Main loop to refresh union applicants
    try:
        while True:
            time.sleep(refresh_time)
            # Activate expel inactive members mode if today is Monday or Tuesday
            expel_inactive_members_mode = datetime.now(tz=timezone(timedelta(hours=8))).weekday() in [0, 1]  # Monday=0, Tuesday=1
            print("[*] Auto expel inactive members mode enabled.", end="\r") if expel_inactive_members_mode else ""
            tab.call_method("HeapProfiler.collectGarbage")

            if player_id:
                sent_payload(json.dumps(["0","0","player:"+player_id,"profile", {"user_id": player_id}]))
                time.sleep(0.5)

            if union_id:
                time.sleep(0.5)
                sent_payload(json.dumps(["0","0","union:"+union_id,"union_contacts",{}]))
                time.sleep(0.5)
                sent_payload(json.dumps(["0","0","union:"+union_id,"union_applicants",{}]))
                time.sleep(0.5)
                if cache_union_members_ids and expel_inactive_members_mode:
                    temp_cache_union_members_ids = cache_union_members_ids.copy()
                    for member_id in list(cache_union_members_ids.keys()):
                        member_name = cache_union_members_ids[member_id][0]
                        if cache_union_members_ids[member_id][1] > expel_inactive_members_time:
                            sent_payload(json.dumps(["0","0","union:"+union_id,"expel_member",{"user_id":member_id}]))
                            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [*] Expel     : {format_name(member_name)} id: {member_id}  (Inactivity)")
                            del temp_cache_union_members_ids[member_id]
                    cache_union_members_ids = temp_cache_union_members_ids
    except KeyboardInterrupt:
        print("\n[!] Stopped.")
    finally:
        tab.stop()