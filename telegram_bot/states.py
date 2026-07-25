from aiogram.fsm.state import State, StatesGroup


class ItemStates(StatesGroup):
    """Состояния FSM для процесса работы с изделиями"""
    
    waiting_datamatrix = State()
    waiting_confirmation = State()
    waiting_regeneration = State()

