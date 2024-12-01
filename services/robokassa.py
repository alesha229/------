import hashlib
from datetime import datetime
from typing import Dict
import config
from urllib.parse import urlencode, quote_plus

class RobokassaPayment:
    def __init__(self):
        # Удаляем кавычки, если они есть
        self.login = config.ROBOKASSA_LOGIN.strip("'\"")
        self.password1 = config.ROBOKASSA_PASSWORD1.strip("'\"")
        self.test_mode = config.ROBOKASSA_TEST_MODE

    def generate_payment_link(self, amount: float, description: str, user_id: int) -> str:
        """Генерация ссылки для оплаты"""
        amount = round(float(amount), 2)
        invoice_id = str(int(datetime.now().timestamp()))
        
        # Формируем базовые параметры
        params = {
            "MerchantLogin": self.login,
            "OutSum": "{:.2f}".format(amount),
            "InvId": invoice_id,
            "Description": quote_plus(description),
            "Encoding": "utf-8"
        }
        
        # Генерируем подпись
        signature_value = self._generate_signature(params["OutSum"], invoice_id)
        params["SignatureValue"] = signature_value
        
        # Добавляем параметр тестового режима
        if self.test_mode:
            params["IsTest"] = "1"
        
        # Формируем URL
        base_url = "https://auth.robokassa.ru/Merchant/Index.aspx"
        return f"{base_url}?{urlencode(params, quote_via=quote_plus)}"

    def _generate_signature(self, amount: str, invoice_id: str) -> str:
        """Генерация подписи для запроса"""
        # Формируем строку для подписи (должна быть в точности как в документации)
        signature_str = f"{self.login}:{amount}:{invoice_id}:{self.password1}"
        # Генерируем MD5-хеш в верхнем регистре
        return hashlib.md5(signature_str.encode('utf-8')).hexdigest().upper()

    def verify_payment(self, amount: float, invoice_id: str, signature: str) -> bool:
        """Проверка подписи при получении уведомления об оплате"""
        amount_str = "{:.2f}".format(float(amount))
        expected_signature = self._generate_signature(amount_str, invoice_id)
        return signature.upper() == expected_signature.upper()
