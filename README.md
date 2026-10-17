# Mobile Banking API
### The Credit Infrastructure for Kenya's Mobile Economy

> One API to launch compliant micro-loans. Built in Thika, for Kenya.

[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![M-Pesa](https://img.shields.io/badge/M--Pesa-43B02A?style=flat&logo=m-pesa&logoColor=white)](https://developer.safaricom.co.ke)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Live Demo:** https://victormawira05-lgmt.github.io/mobile-banking-api/demo  
**API Docs:** `https://api.mobilebanking.co.ke/docs` | **Kaggle Model:** https://www.kaggle.com/code/victormawira05-lgmt/mobile-banking-api-scoring

---

### Try it Out

**1. Affordability Check (The 500 KES Demo)**

```bash
curl -X POST https://api.mobilebanking.co.ke/v1/loans/affordability-check \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 500,
    "currency": "KES",
    "purpose": "Working capital for Mobile Banking API operations - data and transport",
    "gross_income": 24000,
    "existing_debt": 4200,
    "term_months": 1
  }'
