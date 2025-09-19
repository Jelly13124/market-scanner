import sys

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import questionary

import matplotlib.pyplot as plt
import pandas as pd
from colorama import Fore, Style, init
import numpy as np
import itertools

from src.llm.models import LLM_ORDER, OLLAMA_LLM_ORDER, get_model_info, ModelProvider
from src.utils.analysts import ANALYST_ORDER
from src.main import run_hedge_fund
from src.tools.api import (
    get_company_news,
    get_price_data,
    get_prices,
    get_financial_metrics,
    get_insider_trades,
)
from src.utils.display import print_backtest_results, format_backtest_row
from typing_extensions import Callable
from src.utils.ollama import ensure_ollama_and_model
from src.backtesting.engine import BacktestEngine


### Run the Backtest #####
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run backtesting simulation")
    parser.add_argument(
        "--tickers",
        type=str,
        required=False,
        help="Comma-separated list of stock ticker symbols (e.g., AAPL,MSFT,GOOGL)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=(datetime.now() - relativedelta(months=1)).strftime("%Y-%m-%d"),
        help="Start date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=100000,
        help="Initial capital amount (default: 100000)",
    )
    parser.add_argument(
        "--margin-requirement",
        type=float,
        default=0.0,
        help="Margin ratio for short positions, e.g. 0.5 for 50% (default: 0.0)",
    )
    parser.add_argument(
        "--analysts",
        type=str,
        required=False,
        help="Comma-separated list of analysts to use (e.g., michael_burry,other_analyst)",
    )
    parser.add_argument(
        "--analysts-all",
        action="store_true",
        help="Use all available analysts (overrides --analysts)",
    )
    parser.add_argument("--ollama", action="store_true", help="Use Ollama for local LLM inference")

    args = parser.parse_args()

    # Parse tickers from comma-separated string
    tickers = [ticker.strip() for ticker in args.tickers.split(",")] if args.tickers else []

    # Parse analysts from command-line flags
    selected_analysts = None
    if args.analysts_all:
        selected_analysts = [a[1] for a in ANALYST_ORDER]
    elif args.analysts:
        selected_analysts = [a.strip() for a in args.analysts.split(",") if a.strip()]
    else:
        # Choose analysts interactively
        choices = questionary.checkbox(
            "Use the Space bar to select/unselect analysts.",
            choices=[questionary.Choice(display, value=value) for display, value in ANALYST_ORDER],
            instruction="\n\nPress 'a' to toggle all.\n\nPress Enter when done to run the hedge fund.",
            validate=lambda x: len(x) > 0 or "You must select at least one analyst.",
            style=questionary.Style(
                [
                    ("checkbox-selected", "fg:green"),
                    ("selected", "fg:green noinherit"),
                    ("highlighted", "noinherit"),
                    ("pointer", "noinherit"),
                ]
            ),
        ).ask()
        if not choices:
            print("\n\nInterrupt received. Exiting...")
            sys.exit(0)
        else:
            selected_analysts = choices
            print(f"\nSelected analysts: " f"{', '.join(Fore.GREEN + choice.title().replace('_', ' ') + Style.RESET_ALL for choice in choices)}")

    # Select LLM model based on whether Ollama is being used
    model_name = ""
    model_provider = None

    if args.ollama:
        print(f"{Fore.CYAN}Using Ollama for local LLM inference.{Style.RESET_ALL}")

        # Select from Ollama-specific models
        model_name = questionary.select(
            "Select your Ollama model:",
            choices=[questionary.Choice(display, value=value) for display, value, _ in OLLAMA_LLM_ORDER],
            style=questionary.Style(
                [
                    ("selected", "fg:green bold"),
                    ("pointer", "fg:green bold"),
                    ("highlighted", "fg:green"),
                    ("answer", "fg:green bold"),
                ]
            ),
        ).ask()

        if not model_name:
            print("\n\nInterrupt received. Exiting...")
            sys.exit(0)

        if model_name == "-":
            model_name = questionary.text("Enter the custom model name:").ask()
            if not model_name:
                print("\n\nInterrupt received. Exiting...")
                sys.exit(0)

        # Ensure Ollama is installed, running, and the model is available
        if not ensure_ollama_and_model(model_name):
            print(f"{Fore.RED}Cannot proceed without Ollama and the selected model.{Style.RESET_ALL}")
            sys.exit(1)

        model_provider = ModelProvider.OLLAMA.value
        print(f"\nSelected {Fore.CYAN}Ollama{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n")
    else:
        # Use the standard cloud-based LLM selection
        model_choice = questionary.select(
            "Select your LLM model:",
            choices=[questionary.Choice(display, value=(name, provider)) for display, name, provider in LLM_ORDER],
            style=questionary.Style(
                [
                    ("selected", "fg:green bold"),
                    ("pointer", "fg:green bold"),
                    ("highlighted", "fg:green"),
                    ("answer", "fg:green bold"),
                ]
            ),
        ).ask()

        if not model_choice:
            print("\n\nInterrupt received. Exiting...")
            sys.exit(0)
        
        model_name, model_provider = model_choice

        model_info = get_model_info(model_name, model_provider)
        if model_info:
            if model_info.is_custom():
                model_name = questionary.text("Enter the custom model name:").ask()
                if not model_name:
                    print("\n\nInterrupt received. Exiting...")
                    sys.exit(0)

            print(f"\nSelected {Fore.CYAN}{model_provider}{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n")
        else:
            model_provider = "Unknown"
            print(f"\nSelected model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n")

    # Create and run the backtester
    backtester = BacktestEngine(
        agent=run_hedge_fund,
        tickers=tickers,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        model_name=model_name,
        model_provider=model_provider,
        selected_analysts=selected_analysts,
        initial_margin_requirement=args.margin_requirement,
    )

    performance_metrics = backtester.run_backtest()
    performance_df = backtester.analyze_performance()
