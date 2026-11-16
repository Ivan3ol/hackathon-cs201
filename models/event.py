# Base model for events to be scrapped and displayed
class Event:
    __title: str

    def __init__(self, title: str):
        self.__title = title
