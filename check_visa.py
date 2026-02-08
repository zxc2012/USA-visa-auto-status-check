import requests
from bs4 import BeautifulSoup
import ddddocr
import time
import resend
import sys
from PIL import Image
Image.ANTIALIAS = Image.Resampling.LANCZOS
import json
import os
from datetime import datetime

class VisaStateManager:
    def __init__(self, case_number):
        self.case_number = case_number
        self.state_file = f"visa_state_{case_number}.json"
        
    def load_previous_state(self):
        if not os.path.exists(self.state_file):
            return None
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None
            
    def save_current_state(self, state_data):
        state_data['timestamp'] = datetime.now().isoformat()
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)
            
    def has_state_changed(self, current_state):
        previous_state = self.load_previous_state()
        if previous_state is None:
            return True
            
        return (previous_state.get('status') != current_state.get('status') or
                previous_state.get('case_last_updated') != current_state.get('case_last_updated') or
                previous_state.get('message') != current_state.get('message'))

# 设置控制台输出编码为 UTF-8
sys.stdout.reconfigure(encoding='utf-8')
# Fill form
def update_from_current_page(cur_page, name, data):
    ele = cur_page.find(name="input", attrs={"name": name})
    if ele:
        data[name] = ele["value"]
# 修改函数签名以接受 resend_api_key
def get_visa_status(url, visa_type, location, case_number, passport_number, surname, resend_api_key, sender_address, recipient_email, max_retries=3):
    state_manager = VisaStateManager(case_number)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Host": "ceac.state.gov",
    }

    for attempt in range(max_retries):
        try:
            session = requests.Session()

            r = session.get(url=f"{url}/ceacstattracker/status.aspx?App=NIV", headers=headers)

            soup = BeautifulSoup(r.text, features="lxml")

            # Find captcha image
            captcha = soup.find(name="img", id="c_status_ctl00_contentplaceholder1_defaultcaptcha_CaptchaImage")
            image_url = url + captcha["src"]
            img_bytes = session.get(image_url).content
            with open("captcha.png", "wb") as f:
                f.write(img_bytes)

            try:
                ocr = ddddocr.DdddOcr()
                captcha_text = ocr.classification(img_bytes)
                print(f"Attempt {attempt + 1}, recognized captcha: {captcha_text}")
            except AttributeError as e:
                if "ANTIALIAS" in str(e):
                    # 如果是 ANTIALIAS 错误，使用新的 PIL 缩放方法
                    from PIL import Image
                    img = Image.open("captcha.png")
                    img = img.resize((int(img.size[0] * (64 / img.size[1])), 64), Image.Resampling.LANCZOS)
                    img.save("captcha.png")
                    with open("captcha.png", "rb") as f:
                        img_bytes = f.read()
                    captcha_text = ocr.classification(img_bytes)
                else:
                    raise
            data = {
                "ctl00$ToolkitScriptManager1": "ctl00$ContentPlaceHolder1$UpdatePanel1|ctl00$ContentPlaceHolder1$btnSubmit",
                "ctl00_ToolkitScriptManager1_HiddenField": ";;AjaxControlToolkit, Version=4.1.40412.0, Culture=neutral, PublicKeyToken=28f01b0e84b6d53e:en-US:acfc7575-cdee-46af-964f-5d85d9cdcf92:de1feab2:f9cec9bc:a67c2700:f2c8e708:8613aea7:3202a5a2:ab09e3fe:87104b7c:be6fb298",
                "__EVENTTARGET": "ctl00$ContentPlaceHolder1$btnSubmit",
                "__EVENTARGUMENT": "",
                "__LASTFOCUS": "",
                "__VIEWSTATE": "8GJOG5GAuT1ex7KX3jakWssS08FPVm5hTO2feqUpJk8w5ukH4LG/o39O4OFGzy/f2XLN8uMeXUQBDwcO9rnn5hdlGUfb2IOmzeTofHrRNmB/hwsFyI4mEx0mf7YZo19g",
                "__VIEWSTATEGENERATOR": "DBF1011F",
                "__VIEWSTATEENCRYPTED": "",
                "ctl00$ContentPlaceHolder1$Visa_Application_Type": visa_type,
                "ctl00$ContentPlaceHolder1$Location_Dropdown": location,  # Use the correct value
                "ctl00$ContentPlaceHolder1$Visa_Case_Number": case_number,
                "ctl00$ContentPlaceHolder1$Captcha": captcha_text,
                "ctl00$ContentPlaceHolder1$Passport_Number": passport_number,
                "ctl00$ContentPlaceHolder1$Surname": surname,
                "LBD_VCID_c_status_ctl00_contentplaceholder1_defaultcaptcha": "a81747f3a56d4877bf16e1a5450fb944",
                "LBD_BackWorkaround_c_status_ctl00_contentplaceholder1_defaultcaptcha": "1",
                "__ASYNCPOST": "true",
            }

            fields_need_update = [
                "__VIEWSTATE",
                "__VIEWSTATEGENERATOR",
                "LBD_VCID_c_status_ctl00_contentplaceholder1_defaultcaptcha",
            ]
            for field in fields_need_update:
                update_from_current_page(soup, field, data)

            r = session.post(url=f"{url}/ceacstattracker/status.aspx", headers=headers, data=data)

            soup = BeautifulSoup(r.text, features="lxml")
            status_tag = soup.find("span", id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatus")
            if not status_tag:
                continue

            application_num_returned = soup.find("span", id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblCaseNo").string
            assert application_num_returned == case_number
            status = status_tag.string
            
            case_created = soup.find("span", id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblSubmitDate").string
            case_last_updated = soup.find("span", id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatusDate").string

            # 获取详细信息
            message = soup.find("span", id="ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblMessage").string
            
            print(f"签证状态: {status}")
            print(f"Case Created: {case_created}")
            print(f"Case Last Updated: {case_last_updated}")
            print(f"详细信息：{message}")

            current_state = {
                'status': status,
                'case_created': case_created,
                'case_last_updated': case_last_updated,
                'message': message
            }
            
            # 检查状态是否发生变化
            if state_manager.has_state_changed(current_state):
                print("状态发生变化，发送邮件通知...")
                # 使用传入的 API Key
                resend.api_key = resend_api_key
                sender_name = "Visa_bot"
                sender_email = f"{sender_name} <{sender_address}>"
                params: resend.Emails.SendParams = {
                    "from": sender_email,
                    "to": [recipient_email], # 也可以考虑将收件人邮箱设为环境变量
                    "subject": f"签证状态更新通知: {case_last_updated}",
                    "html": f"签证状态: {status}<br>Case Created: {case_created}<br>Case Last Updated: {case_last_updated}<br>详细信息：{message}",
                }
                resend.Emails.send(params)
                # 保存新状态
                state_manager.save_current_state(current_state)
            else:
                print("状态未发生变化，跳过邮件通知")

            
            break

        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt == max_retries - 1:
                print("Maximum retries reached, exiting.")
                raise
            else:
                print("Waiting 5 seconds before retry...")
                time.sleep(5)

if __name__ == "__main__":
    # 从环境变量读取敏感信息
    case_number = os.environ.get("VISA_CASE_NUMBER")
    passport_number = os.environ.get("PASSPORT_NUMBER")
    surname = os.environ.get("SURNAME")
    resend_api_key = os.environ.get("RESEND_API_KEY")
    sender_address = os.environ.get("SENDER_ADDRESS")
    # 可选：从环境变量读取收件人邮箱
    recipient_email = os.environ.get("RECIPIENT_EMAIL") # 提供默认值

    # 检查必要的环境变量是否已设置
    if not all([case_number, passport_number, surname, resend_api_key, sender_address]):
        print("错误：请设置 VISA_CASE_NUMBER, PASSPORT_NUMBER, SURNAME, RESEND_API_KEY 和 SENDER_ADDRESS 环境变量。")
        sys.exit(1)

    url = "https://ceac.state.gov"
    visa_type = "NIV"  # 这些可以保持硬编码，或者也设为环境变量
    location = "GUZ"   # 这些可以保持硬编码，或者也设为环境变量
    max_retries = 3

    # 将读取到的值传递给函数
    get_visa_status(url, visa_type, location, case_number, passport_number, surname, resend_api_key, sender_address, recipient_email, max_retries)

