from playwright.sync_api import sync_playwright
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

# 修改函数签名以接受 resend_api_key
def get_visa_status(url, visa_type, location, case_number, passport_number, surname, resend_api_key, sender_address, recipient_email, max_retries=3):
    state_manager = VisaStateManager(case_number)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        for attempt in range(max_retries):
            try:
                page = browser.new_page()
                page.goto(url)

                page.select_option("#Visa_Application_Type", visa_type)
                page.select_option("#Location_Dropdown", location)
                page.fill("#Visa_Case_Number", case_number)
                page.fill("#Passport_Number", passport_number)
                page.fill("#Surname", surname)

                captcha_img = page.locator("#c_status_ctl00_contentplaceholder1_defaultcaptcha_CaptchaImage")
                img_bytes = captcha_img.screenshot(path="captcha.png")

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

                page.fill("#Captcha", captcha_text)
                page.click("#ctl00_ContentPlaceHolder1_btnSubmit")

                # 检查是否成功提交
                try:
                    error_message = page.locator("//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'invalid') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'incorrect')]")
                    if error_message.count() > 0:
                        print("验证码错误，正在重试...")
                        page.reload()
                        page.wait_for_selector("#Visa_Application_Type")
                        continue
                except:
                    pass

                page.wait_for_selector("#ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatus", timeout=30000)

                # 获取签证状态
                status = page.inner_text("#ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatus")
                
                # 获取 Case Created 时间
                case_created = page.inner_text("#ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblSubmitDate")

                # 获取 Case Last Updated 时间
                case_last_updated = page.inner_text("#ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblStatusDate")

                # 获取详细信息
                message = page.inner_text("#ctl00_ContentPlaceHolder1_ucApplicationStatusView_lblMessage")
                
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
                    
                else:
                    print("状态未发生变化，跳过邮件通知")
                # 保存新状态
                    state_manager.save_current_state(current_state)
                
                break

            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_retries - 1:
                    print("Maximum retries reached, exiting.")
                    raise
                else:
                    print("Waiting 5 seconds before retry...")
                    time.sleep(5)
                    page.reload()
                    page.wait_for_selector("#Visa_Application_Type")

        browser.close()

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

    url = "https://ceac.state.gov/CEACStatTracker/Status.aspx"
    visa_type = "NIV"  # 这些可以保持硬编码，或者也设为环境变量
    location = "GUZ"   # 这些可以保持硬编码，或者也设为环境变量
    max_retries = 3

    # 将读取到的值传递给函数
    get_visa_status(url, visa_type, location, case_number, passport_number, surname, resend_api_key, sender_address, recipient_email, max_retries)
