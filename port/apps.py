from django.apps import AppConfig


class PortConfig(AppConfig):
    name = 'port'
    def ready(self):
        import port.signals