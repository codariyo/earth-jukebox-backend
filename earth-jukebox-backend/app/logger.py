"""Kirmizi renkli ve ayracli terminal loglama sistemi.

Kullanicinin istegi uzerine cekilen linkleri terminalde kirmizi renkte ve
ustunde/altinda '------' ayraclariyla yazdirir. Windows terminal renk destegi
colorama ile acilir.
"""
from colorama import Fore, Style, init

# Windows terminal renk destegini baslat
init(autoreset=True)

SEPARATOR = "-" * 80


def log_nasa_request(target_url: str, request_type: str = "NASA GIBS ISTEGI") -> None:
    """Linki ayraclar arasinda kirmizi yazar."""
    print(f"\n{Fore.RED}{SEPARATOR}")
    print(f"{Fore.RED}[{request_type}]")
    print(f"{Fore.RED}URL: {target_url}")
    print(f"{Fore.RED}{SEPARATOR}\n{Style.RESET_ALL}", flush=True)
