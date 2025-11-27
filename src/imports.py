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

import requests
import matplotlib

load_dotenv()
class Config:
    STOCKS_API = {
        'HOST': os.getenv('STOCKSAPI_HOST'),
        'PORT': os.getenv('STOCKSAPI_PORT'),
        'KEY': os.getenv('STOCKSAPI_PRIVATE.KEY')
    }