import os
import sys
import json
import time
import threading
import logging

from datetime import datetime
from dotenv import load_dotenv

import pandas as pd
import numpy as np

import yfinance as yf

import requests
import matplotlib

import selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()
class Config:
    STOCKS_API = {
        'HOST': os.getenv('STOCKSAPI_HOST'),
        'PORT': os.getenv('STOCKSAPI_PORT'),
        'KEY': os.getenv('STOCKSAPI_PRIVATE.KEY')
    }