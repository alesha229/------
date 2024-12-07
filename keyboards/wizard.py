from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict, Optional

def create_wizard_keyboard(items: List[Dict]) -> Optional[InlineKeyboardMarkup]:
    """Create keyboard from wizard items"""
    if not items:
        return None
        
    keyboard = []
    current_row = []
    
    for item in items:
        if len(current_row) == 2:
            keyboard.append(current_row)
            current_row = []
            
        callback_data = f"wizard_{item['key']}"
        current_row.append(
            InlineKeyboardButton(
                text=str(item['value']),
                callback_data=callback_data
            )
        )
    
    if current_row:
        keyboard.append(current_row)
        
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def create_modifications_keyboard(modifications: List[Dict], page: int = 1, items_per_page: int = 5) -> Optional[InlineKeyboardMarkup]:
    """Create keyboard with modifications and pagination"""
    if not modifications:
        return None
        
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_items = modifications[start_idx:end_idx]
    
    keyboard = []
    
    # Add modification buttons
    for item in page_items:
        keyboard.append([
            InlineKeyboardButton(
                text=str(item['value']),
                callback_data=f"mod_{item['key']}"
            )
        ])
    
    # Add pagination if needed
    nav_buttons = []
    total_pages = (len(modifications) + items_per_page - 1) // items_per_page
    
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"page_{page-1}"
            )
        )
    
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Вперед ▶️",
                callback_data=f"page_{page+1}"
            )
        )
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
