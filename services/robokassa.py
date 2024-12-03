from hashlib import md5
from typing import Dict, Any
from decimal import Decimal
from urllib.parse import urlencode
import os
import config
from utils.logger import logger
from utils.metrics import metrics

class RobokassaPayment:
    """Класс для работы с платежной системой Robokassa"""
    
    def __init__(self):
        """Инициализация с параметрами из конфигурации"""
        # Получаем и очищаем значения от кавычек
        self.login = os.getenv("ROBOKASSA_LOGIN", "").strip("'\"")
        self.password1 = os.getenv("ROBOKASSA_PASSWORD1", "").strip("'\"")
        self.password2 = os.getenv("ROBOKASSA_PASSWORD2", "").strip("'\"")
        self.test_mode = bool(int(os.getenv("ROBOKASSA_TEST_MODE", "1")))
        
        # URL для формирования ссылок
        self.base_url = "https://auth.robokassa.ru/Merchant/Index.aspx"
        
        logger.info(
            "robokassa_initialized",
            test_mode=self.test_mode
        )
    
    def generate_payment_link(
        self,
        order_id: int,
        amount: Decimal,
        description: str
    ) -> str:
        """Генерация ссылки для оплаты"""
        try:
            # Формируем подпись
            signature = self._generate_signature(order_id, amount)
            
            # Параметры для URL
            params = {
                "MerchantLogin": self.login,
                "OutSum": float(amount),
                "InvId": order_id,
                "Description": description,
                "SignatureValue": signature,
                "IsTest": 1 if self.test_mode else 0
            }
            
            # Формируем URL
            payment_url = f"{self.base_url}?{urlencode(params)}"
            
            logger.info(
                "payment_link_generated",
                order_id=order_id,
                amount=float(amount)
            )
            metrics.payment_links_generated.inc()
            
            return payment_url
            
        except Exception as e:
            logger.error(
                "payment_link_generation_error",
                error=str(e),
                order_id=order_id
            )
            metrics.error_count.labels(type="payment_link").inc()
            raise
    
    def verify_payment(
        self,
        order_id: int,
        amount: Decimal,
        signature: str
    ) -> bool:
        """Проверка подписи платежа"""
        try:
            expected_signature = self._generate_signature(
                order_id,
                amount,
                password=self.password2
            )
            
            is_valid = signature.lower() == expected_signature.lower()
            
            if is_valid:
                metrics.successful_payments.inc()
                logger.info(
                    "payment_verified",
                    order_id=order_id,
                    amount=float(amount)
                )
            else:
                metrics.failed_payments.inc()
                logger.warning(
                    "payment_verification_failed",
                    order_id=order_id,
                    amount=float(amount)
                )
            
            return is_valid
            
        except Exception as e:
            logger.error(
                "payment_verification_error",
                error=str(e),
                order_id=order_id
            )
            metrics.error_count.labels(type="payment_verification").inc()
            raise
    
    def _generate_signature(
        self,
        order_id: int,
        amount: Decimal,
        password: str = None
    ) -> str:
        """Генерация подписи для запроса"""
        if password is None:
            password = self.password1
            
        # Формируем строку для подписи
        signature_str = f"{self.login}:{float(amount)}:{order_id}:{password}"
        
        # Генерируем MD5 хеш
        return md5(signature_str.encode()).hexdigest()
