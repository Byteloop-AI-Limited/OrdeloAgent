# Plan: per-order Stripe success/cancel URLs (payment-service + OrdeloAgent + restaurant-frontend)

Written 2026-10-08. Decisions agreed with the owner in a grilling session (Q1–Q12 below).
Code references are from:

| Repo | Path on owner's Mac | Branch to work on | Base |
|---|---|---|---|
| payment-service (Go, Lambda) | `/Users/basavaraj/bloop/payment-service` | `feature/support-dynamic-successUrl` (exists) | `main` @ `58158ca` |
| OrdeloAgent (Python, FastAPI) | `/Users/basavaraj/bloop/OrdeloAgent` | `feature/dynamic-payment-return-urls` (create) | `dev` @ `adf77dd` |
| restaurant-frontend (Next.js) | `/Users/basavaraj/bloop/restaurant-frontend` | `feature/dynamic-payment-return-urls` (create) | `dev` |

Commit locally, **do not push**, until the owner has tested. Commit format `type: summary`.

---

## 1. Problem

After paying on Stripe Checkout, a **web** customer lands on the restaurant's WhatsApp `wa.me` link instead of the web order page. Known gap D26 (`OrdeloAgent/plans/ordelo-agg-plan-cc.md` §13.1).

Root cause (verified in code): the Stripe dashboard has no setting for this. Every Checkout Session gets its `success_url`/`cancel_url` from the API call that creates it, and the payment service always uses fixed per-restaurant values:

- `payment-service/internal/stripe/payment.go` L122–123: `SuccessURL: stripe.String(p.successURL)`, `CancelURL: stripe.String(p.cancelURL)`.
- Those come from `getPaymentAPI(restRef)` in `internal/transport/http/handler.go` L404–415. It reads `selectedRestaurant.SuccessURL/CancelURL` from config.
- The config values live in two places:
  - `internal/config/config.go` `ensureRestaurantDefaults()` L191–~240. Production loads from Secrets Manager, then applies these defaults.
  - `internal/config/config.yaml`. This is the fallback when AWS is unavailable. It gives BNAT `wa.me/message/F7QYDTUOIVCNI1`, while the code default sends BNAT to the menu page.
- `PaymentRequestBody` (`handler.go` L47–61) has no URL fields, so a caller can't override them.

The frontend landing page already exists and works: `restaurant-frontend/app/(web)/checkout/return/page.tsx` → `components/ordelo/PaymentReturn.tsx`. It polls `/api/web/orders/{n}` until the payment is authorised, then calls `router.replace(view.page_path)`. Cancel already has a resume page: `app/(web)/checkout/page.tsx` handles `?resume=1`.

## 2. Decisions (agreed)

| # | Decision |
|---|---|
| Q1 | `success_url` and `cancel_url` are **optional, independently**. A missing (or blank) field falls back to that restaurant's configured URL. Neither sent means behaviour is exactly as today. |
| Q2 | Allowed hosts live **in code** (change = commit + deploy): `restaurant.ordelo.app`, `restaurant-test.ordelo.app`, `wa.me`. |
| Q3 | A sent URL that fails the check returns **400 before any Stripe session is created**. No customer payment can exist yet, so nothing is lost. The rejected URL is logged. |
| Q4 | OrdeloAgent sends URLs from **both** callers: web checkout and the WhatsApp menu-page path (`order_hooks.create_order`). |
| Q5/Q6 | The web storefront base comes from ordelo_config key **`WEB_STOREFRONT_URL`**, the full URL with no trailing slash (value `https://restaurant-test.ordelo.app`). The WhatsApp return links are a **static map in OrdeloAgent code** keyed by rest_ref, mirroring payment-service `config.yaml`. A missing key or an unknown rest_ref means that caller sends **no** URLs, so the payment-service defaults apply. |
| Q7 | BNAT's WhatsApp link is `https://wa.me/message/F7QYDTUOIVCNI1`. This is a deliberate change: deployed BNAT currently goes to the menu page. |
| Q8 | Local run: a new `payment-service/cmd/local/main.go` HTTP adapter on `:4041` that calls the same `handler.Generic`. It is not part of the Lambda build (`buildspec.yml` builds `main.go` only). |
| Q9 | The local adapter loads **only the embedded `config.yaml`** (never Secrets Manager) and refuses to start if any Stripe key starts with `sk_live_`/`rk_live_`. |
| Q10 | No new local-only settings in OrdeloAgent and no change to the `ordelo-agent-env` secret. For local testing the owner **temporarily hard-codes** `ms_settings.stripe_url_test` (§6.1) and does not commit it. The existing test routing (overwatch + `TEST_PAYMENT_REST_REFS`) decides which orders hit it. |
| Q11 | Delete the "Stripe may open the restaurant's WhatsApp page…" note from the frontend. Deploy the frontend last. |
| Q12 | Branches as in the table above; commit, no push. |

Compatibility fact: Go's `encoding/json` ignores unknown fields. The **deployed** payment service therefore ignores `success_url`/`cancel_url` until it is redeployed, so OrdeloAgent can ship before or after the payment service.

Considered and kept separate: ordelo_config already has `RESTAURANT_MENU_APP_URL` (dashboard links, `config/params.py`). Q6 chose a dedicated `WEB_STOREFRONT_URL` so that web return links don't move when the menu/dashboard host is switched for local testing (runbook §5).

---

## 3. payment-service changes

Module: `github.com/Byteloop-AI-Limited/payment-service`, `go 1.20` (**no `slices` package**, so use loops). Deps already present: `aws-lambda-go v1.47.0`, `stripe-go/v74`, `viper`.

### 3.1 New file `internal/config/return_hosts.go`

```go
package config

// AllowedReturnHosts are the only hosts a caller may send as success_url /
// cancel_url. Exact match, https only. Changing this list needs a commit and a
// deploy (decision Q2). Production loads Secrets Manager and never reads
// config.yaml, so this list must live in code, not YAML.
var AllowedReturnHosts = []string{
	"restaurant.ordelo.app",
	"restaurant-test.ordelo.app",
	"wa.me",
}
```

### 3.2 New file `internal/transport/http/return_urls.go`

```go
package http

import (
	"fmt"
	"net/url"
	"strings"

	"github.com/Byteloop-AI-Limited/payment-service/internal/config"
)

const maxReturnURLLen = 2048

// resolveReturnURLs picks the Checkout Session success/cancel URLs.
// Each field is independent (decision Q1): blank -> the restaurant default,
// otherwise it must pass checkReturnURL or the request is rejected (Q3).
// Restaurant defaults are not re-validated, so existing behaviour is unchanged.
func resolveReturnURLs(rest config.RestaurantConfig, success, cancel string, allowed []string) (string, string, string, error) {
	s, c := strings.TrimSpace(success), strings.TrimSpace(cancel)
	source := "request"
	if s == "" && c == "" {
		source = "default"
	} else if s == "" || c == "" {
		source = "partial"
	}
	if s == "" {
		s = rest.SuccessURL
	} else if err := checkReturnURL(s, allowed); err != nil {
		return "", "", "", fmt.Errorf("success_url: %w", err)
	}
	if c == "" {
		c = rest.CancelURL
	} else if err := checkReturnURL(c, allowed); err != nil {
		return "", "", "", fmt.Errorf("cancel_url: %w", err)
	}
	return s, c, source, nil
}

func checkReturnURL(raw string, allowed []string) error {
	if len(raw) > maxReturnURLLen {
		return fmt.Errorf("longer than %d characters", maxReturnURLLen)
	}
	u, err := url.Parse(raw)
	if err != nil {
		return fmt.Errorf("not a valid URL")
	}
	if u.Scheme != "https" {
		return fmt.Errorf("scheme must be https")
	}
	if u.User != nil {
		return fmt.Errorf("user info not allowed")
	}
	if u.Port() != "" {
		return fmt.Errorf("explicit port not allowed")
	}
	host := strings.ToLower(u.Hostname())
	for _, h := range allowed {
		if host == h {
			return nil
		}
	}
	return fmt.Errorf("host %q not allowed", host)
}
```

Why each check: `u.Hostname()` is the real host, so `https://wa.me@evil.com` has host `evil.com` and is rejected. Exact match means `restaurant.ordelo.app.evil.com` is rejected. The service doesn't check the caller's token (plan F12), so without the list anyone with the endpoint URL could create real Checkout Sessions that send customers to a site of their choosing after paying.

### 3.3 Edit `internal/transport/http/handler.go`

1. **`PaymentRequestBody` (L47–61):** add after `RestRef` (L60):
   ```go
   	SuccessURL                 string        `json:"success_url,omitempty"`
   	CancelURL                  string        `json:"cancel_url,omitempty"`
   ```
2. **`Generic`, L135:** pass the new fields:
   ```go
   return h.Payment(body.RestRef, body.Items, threadID, orderNumber, body.Currency, body.Action, body.Notes, body.Recipient, body.RiderCode, body.ManualModeCapture, body.SuccessURL, body.CancelURL)
   ```
3. **`Payment` signature, L349:** add `successURL, cancelURL string` at the end.
4. **`Payment` body:** replace L363 `paymentApi, err := h.getPaymentAPI(restRef)` with:
   ```go
   	rest := h.cfg.GetRestaurant(restRef)
   	success, cancel, source, err := resolveReturnURLs(rest, successURL, cancelURL, config.AllowedReturnHosts)
   	if err != nil {
   		log.Printf("CreatePaymentURL rejected: restRef=%q orderID=%q err=%v successURL=%q cancelURL=%q", restRef, orderID, err, successURL, cancelURL)
   		return events.APIGatewayProxyResponse{
   			StatusCode: http.StatusBadRequest,
   			Body:       fmt.Sprintf(`{"error":%q}`, "invalid return URL: "+err.Error()),
   		}, nil
   	}
   	log.Printf("CreatePaymentURL returnURLs: orderID=%q source=%s success=%q cancel=%q", orderID, source, success, cancel)

   	paymentApi, err := h.getPaymentAPIWithURLs(restRef, success, cancel)
   ```
   The rest of `Payment` (L364–401) stays as is.
5. **`getPaymentAPI` (L404–415):** keep it for capture (L161) and cancel (L235), which don't need URLs. Make it a thin wrapper:
   ```go
   func (h *Handler) getPaymentAPI(restRef string) (stripe.PaymentApi, error) {
   	r := h.cfg.GetRestaurant(restRef)
   	return h.getPaymentAPIWithURLs(restRef, r.SuccessURL, r.CancelURL)
   }

   func (h *Handler) getPaymentAPIWithURLs(restRef, successURL, cancelURL string) (stripe.PaymentApi, error) {
   	selectedRestaurant := h.cfg.GetRestaurant(restRef)
   	log.Printf(/* existing log line, but print successURL/cancelURL args */)
   	return stripe.NewPayment(selectedRestaurant.StripeKey, selectedRestaurant.RestaurantAccountID, successURL, cancelURL, h.repo)
   }
   ```
`internal/stripe/payment.go` needs **no change**, because `NewPayment` already takes the URLs.

The validation sits after the existing `len(body.Items)` / `threadID` checks in `Generic`. It only runs on the create-session path, never on capture, cancel, print-only or webhook.

### 3.4 Edit `internal/config/config.go`: split out embedded loading (for the local runner)

The YAML tail of `Init()` (after the Secrets Manager block, from `viper.SetConfigType("yaml")` to `return &config`) moves into an exported function. `Init()` then ends with `return InitEmbedded()`. Behaviour is unchanged.

```go
// InitEmbedded loads only the embedded config.yaml, never Secrets Manager.
// Used by cmd/local so a laptop never picks up production (live) keys.
func InitEmbedded() *Config {
	viper.SetConfigType("yaml")
	if err := viper.ReadConfig(bytes.NewBuffer(configFile)); err != nil {
		log.Printf("Failed to read embedded config: %v. Using defaults...\n", err)
	} else {
		log.Println("Embedded config file loaded successfully")
	}
	var config Config
	if err := viper.Unmarshal(&config); err != nil {
		log.Fatalf("Failed to unmarshal configuration: %v\n", err)
	}
	config.ensureRestaurantDefaults()
	return &config
}

// AssertTestKeysOnly fails if any loaded Stripe key is a live key (decision Q9).
func (c *Config) AssertTestKeysOnly() error {
	check := func(name, key string) error {
		if strings.HasPrefix(key, "sk_live_") || strings.HasPrefix(key, "rk_live_") {
			return fmt.Errorf("live Stripe key in %s; local runs are test mode only", name)
		}
		return nil
	}
	if err := check("stripekey", c.StripeKey); err != nil { return err }
	if err := check("stripetestkey", c.StripeTestKey); err != nil { return err }
	for ref, r := range c.Restaurants {
		if err := check("restaurants."+ref+".stripekey", r.StripeKey); err != nil { return err }
	}
	return nil
}
```
`fmt` must be added to the imports. Today the embedded YAML holds only `sk_test_` keys (checked 2026-10-08).

### 3.5 New file `cmd/local/main.go`: local HTTP adapter on :4041

`main.go` (Lambda) is untouched. `buildspec.yml` runs `go build ... -o bootstrap main.go`, so `cmd/local` is never deployed.

```go
// Local HTTP runner for the payment Lambda. Not deployed (buildspec builds main.go).
// Converts net/http requests into the APIGatewayProxyRequest API Gateway sends,
// then calls the same handler.Generic the Lambda uses.
package main

import (
	"context"
	"io"
	"log"
	nethttp "net/http"
	"os"
	"regexp"

	"github.com/Byteloop-AI-Limited/payment-service/internal/common"
	"github.com/Byteloop-AI-Limited/payment-service/internal/config"
	"github.com/Byteloop-AI-Limited/payment-service/internal/stripe"
	transport "github.com/Byteloop-AI-Limited/payment-service/internal/transport/http"
	"github.com/Byteloop-AI-Limited/payment-service/storage"
	"github.com/aws/aws-lambda-go/events"
)

// OrdeloAgent calls {base}/threads/{t}/orders/{o}/payment-url; the base may or
// may not carry an API Gateway stage such as /prod.
var paymentPath = regexp.MustCompile(`^(?:/[^/]+)?/threads/([^/]+)/orders/([^/]+)/payment-url/?$`)

func toProxyRequest(r *nethttp.Request, body []byte) events.APIGatewayProxyRequest {
	q := map[string]string{}
	for k, v := range r.URL.Query() {
		if len(v) > 0 {
			q[k] = v[0]
		}
	}
	if m := paymentPath.FindStringSubmatch(r.URL.Path); m != nil {
		q["threadID"], q["orderID"] = m[1], m[2]
	}
	h := map[string]string{}
	for k, v := range r.Header {
		if len(v) > 0 {
			h[k] = v[0]
		}
	}
	return events.APIGatewayProxyRequest{
		HTTPMethod: r.Method, Path: r.URL.Path, Headers: h,
		QueryStringParameters: q, Body: string(body),
	}
}

func main() {
	cfg := config.InitEmbedded()
	if err := cfg.AssertTestKeysOnly(); err != nil {
		log.Fatal(err)
	}
	repo := storage.NewStorage(cfg.SupabaseApiKey)
	webhook, err := stripe.NewWebhook(cfg.StripeKey, cfg.EmailAppSecret, repo, cfg)
	if err != nil {
		log.Fatal(err)
	}
	handler := transport.NewHandler(webhook, cfg.EmailAppSecret, cfg, repo)

	port := os.Getenv("PORT")
	if port == "" {
		port = "4041"
	}
	nethttp.HandleFunc("/", func(w nethttp.ResponseWriter, r *nethttp.Request) {
		body, _ := io.ReadAll(r.Body)
		ctx := context.WithValue(r.Context(), common.ServiceTokenKey, cfg.ServiceToken)
		resp, err := handler.Generic(ctx, toProxyRequest(r, body))
		if err != nil {
			log.Printf("handler error: %v", err)
		}
		for k, v := range resp.Headers {
			w.Header().Set(k, v)
		}
		if resp.StatusCode == 0 {
			resp.StatusCode = nethttp.StatusInternalServerError
		}
		w.WriteHeader(resp.StatusCode)
		_, _ = w.Write([]byte(resp.Body))
	})
	log.Printf("payment-service local runner on http://localhost:%s (embedded config, Stripe test keys only)", port)
	log.Fatal(nethttp.ListenAndServe(":"+port, nil))
}
```
Note: the unused `gracefulShutdown` helper in `main.go` (marked TODO-remove) can stay; don't touch `main.go`.

### 3.6 Tests (payment-service)

Existing tests: `internal/config/bnat_config_test.go`, `internal/stripe/webhook_test.go`. Both must still pass.

**New `internal/transport/http/return_urls_test.go`**, a table test of `resolveReturnURLs`. Use `rest := config.RestaurantConfig{SuccessURL: "https://wa.me/message/DEF", CancelURL: "https://wa.me/message/DEF"}` and `allowed := config.AllowedReturnHosts`.

| Case | success | cancel | Expect |
|---|---|---|---|
| neither | `""` | `""` | defaults, source `default` |
| blanks | `"  "` | `"  "` | defaults, source `default` |
| success only | `https://restaurant-test.ordelo.app/checkout/return?order=ELAS-ABCD-1` | `""` | given success, default cancel, source `partial` |
| cancel only | `""` | `https://restaurant-test.ordelo.app/checkout?resume=1` | default success, given cancel, `partial` |
| both | web success + web cancel | | both as given, `request` |
| wa.me | `https://wa.me/message/AIDICBLAE4KZH1` (both) | | accepted |
| uppercase host | `https://RESTAURANT-TEST.ordelo.app/x` | | accepted |
| http | `http://restaurant-test.ordelo.app/x` | | error |
| foreign host | `https://evil.com/x` | | error |
| lookalike | `https://restaurant.ordelo.app.evil.com/x` | | error |
| userinfo | `https://wa.me@evil.com/x` | | error |
| port | `https://restaurant.ordelo.app:8443/x` | | error |
| too long | `https://wa.me/` + 2100×`a` | | error |
| bad success, good cancel | `https://evil.com` | web cancel | error mentions `success_url` |

**New `internal/config/local_config_test.go`:** `AssertTestKeysOnly` passes for `sk_test_` keys and fails for `sk_live_` in the top-level and per-restaurant keys. Also, `InitEmbedded()` returns `elas`/`sfcs`/`bnat` with non-empty URLs.

**New `cmd/local/main_test.go`:** `toProxyRequest` maps both `/threads/T1/orders/ELAS-ABCD-1/payment-url` and `/prod/threads/T1/orders/ELAS-ABCD-1/payment-url` to `threadID=T1`, `orderID=ELAS-ABCD-1`. It passes `?webhookID=x` through, and keeps the body.

Run: `go vet ./... && go test ./...`

---

## 4. OrdeloAgent changes

Repo rules (CLAUDE.md):
- Supabase REST (`client_ordelo`) is blocking, so wrap it in `asyncio.to_thread()` in async code.
- Ruff F-rules.
- pytest + pytest-asyncio.

### 4.1 `config/feature_flags.py`: add a string reader (same 60 s cache pattern)

Add after `config_csv` (≈L93), and extend `reset_feature_flag_cache` (≈L95) to clear `_STR_CACHE` too:

```python
_STR_CACHE: dict[str, tuple[str | None, float]] = {}


def _read_str(key: str) -> str | None:
    response = (
        client_ordelo.table("ordelo_config")
        .select("config_value")
        .eq("config_key", key)
        .execute()
    )
    rows = response.data or []
    value = str(rows[0].get("config_value") or "").strip() if rows else ""
    return value or None


async def config_str(key: str) -> str | None:
    """A single ``ordelo_config`` value (cached 60 s). Missing/blank/failed lookup -> None."""
    cached = _STR_CACHE.get(key)
    now = time.monotonic()
    if cached and now - cached[1] < _FLAG_CACHE_TTL_SECS:
        return cached[0]
    try:
        value = await asyncio.to_thread(_read_str, key)
    except Exception as err:  # noqa: BLE001 - a failed lookup means "not set"
        logger.warning(f"config {key}: lookup failed, treating as unset: {err}")
        value = None
    _STR_CACHE[key] = (value, now)
    return value
```
Update the module docstring "Functions" list and the "What remains in ordelo_config" comment (L26–28) to mention `WEB_STOREFRONT_URL`.

### 4.2 New module `utils_common/payment_ms/return_urls.py`

```python
"""
Stripe Checkout return URLs sent to the payment service.
  . web_return_urls - web orders return to the storefront's /checkout/return page
  . wa_return_urls  - WhatsApp menu-page orders return to the restaurant's WhatsApp chat
  . None from either means "send nothing": the payment service uses its per-restaurant defaults.
Functions:
  . web_return_urls
  . wa_return_urls
"""

from urllib.parse import quote

from config.feature_flags import config_str

WEB_STOREFRONT_URL = "WEB_STOREFRONT_URL"

# Mirrors payment-service internal/config/config.yaml successurl/cancelurl and
# restaurant-frontend config/whatsapp.ts PAYMENT_COMPLETE (decision Q6/Q7).
WA_PAYMENT_RETURN_URLS: dict[str, str] = {
    "ELAS": "https://wa.me/message/AIDICBLAE4KZH1",
    "SFCS": "https://wa.me/message/KLHBN7UOKO7UE1",
    "BNAT": "https://wa.me/message/F7QYDTUOIVCNI1",
}


async def web_return_urls(order_number: str) -> dict[str, str] | None:
    base = await config_str(WEB_STOREFRONT_URL)
    if not base:
        return None
    base = base.rstrip("/")
    return {
        "success_url": f"{base}/checkout/return?order={quote(order_number, safe='')}",
        "cancel_url": f"{base}/checkout?resume=1",
    }


def wa_return_urls(rest_ref: str) -> dict[str, str] | None:
    url = WA_PAYMENT_RETURN_URLS.get((rest_ref or "").upper())
    return {"success_url": url, "cancel_url": url} if url else None
```
`/checkout/return` validates the order number against `^[A-Z0-9]+-[A-Z]{4}-\d+$` (`app/(web)/checkout/return/page.tsx`). Order numbers are already in that form (`ELAS-ABCD-12`).

### 4.3 `utils_common/payment_ms/payment.py`: optional `return_urls`

- **`generate_payment_intent_url` (L26):** use `async def generate_payment_intent_url(food_order: FoodOrder, return_urls: dict[str, str] | None = None):`. After `intent_payload = await food_order.gen_payment_intent_payload()` (L37), add:
  ```python
      if return_urls:
          intent_payload.update(return_urls)
  ```
- **`generate_takeaway_manual_payment_url` (L71):** add the same `return_urls=None` parameter and pass it through to `_generate_takeaway_payment_url(..., return_urls=return_urls)`.
- **`generate_automatic_payment_url` (L52):** add nothing. It's used for print-only/automatic jobs (`takeaway_hooks.py` L452) where the URL doesn't matter.
- **`_generate_takeaway_payment_url` (L80):** add the keyword argument `return_urls: dict[str, str] | None = None`. After building `intent_payload` (≈L101), add `if return_urls: intent_payload.update(return_urls)`.
- Update the module docstring.

If no URLs are passed, the payload is byte-for-byte unchanged. The existing exact-payload assertion in `tests/utils_common/payment_ms/test_payment.py` L49–70 must still pass.

### 4.4 `watomation/routers/order_hooks.py`: WhatsApp menu-page path

In `create_order` (route `POST /create-order/{rest_ref}`, L222), the payment branch is at L298–301. Change it to:

```python
    return_urls = wa_return_urls(food_order.rest_ref)
    if food_order.action == "delivery":
        payment_intent_url = await generate_payment_intent_url(food_order, return_urls=return_urls)
    elif food_order.action == "takeaway":
        payment_intent_url = await generate_takeaway_manual_payment_url(food_order, return_urls=return_urls)
```
Add the import `from utils_common.payment_ms.return_urls import wa_return_urls` next to the existing `utils_common.payment_ms.payment` import (L49). `FoodOrder.rest_ref` (`food_order_pymodel.py` L226) returns lowercase, and the map lookup upper-cases it.

### 4.5 `utils_common/web_ordering/web_checkout.py`: web checkout

In `create(req, key)` (L272), the payment URL is generated inside the second transaction (L418). Read the URLs **before** that transaction, so the ordelo_config lookup doesn't run while the advisory lock is held:

```python
        return_urls = await web_return_urls(attempt["order_number"])   # new, just above L418
        async with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            ...
                url = await generator(food, return_urls=return_urls)     # was: await generator(food)  (L438)
```
Add the import `from utils_common.payment_ms.return_urls import web_return_urls` near L21–24.

The stored quote (`web_order_request.quote`) is unchanged: replays return the stored `payment_url`, and only a missing URL is regenerated (D22).

### 4.6 `tests/conftest.py`: keep tests off Supabase

The autouse fixture `feature_flags` (≈L175) patches only `_read_flag`. Add a sibling autouse fixture:

```python
@pytest.fixture(autouse=True)
def config_values(monkeypatch):
    """ordelo_config string values; empty (all unset) by default.
    Tests set one with ``config_values["WEB_STOREFRONT_URL"] = "https://restaurant-test.ordelo.app"``.
    """
    from config import feature_flags as flags_module

    values: dict[str, str] = {}
    monkeypatch.setattr(flags_module, "_read_str", lambda key: values.get(key))
    flags_module.reset_feature_flag_cache()
    yield values
    flags_module.reset_feature_flag_cache()
```

### 4.7 Tests (OrdeloAgent)

- **`tests/utils_common/payment_ms/test_payment.py`** (extend):
  - Existing tests are unchanged and must pass, which proves the no-URL payload is identical.
  - `generate_takeaway_manual_payment_url(order, return_urls={...})`: the payload contains `success_url`/`cancel_url` and every existing key.
  - `generate_payment_intent_url(order, return_urls={...})`: same check. Use a fake with `payment_uri`, `async gen_payment_intent_payload()` returning `{"items": [...], "currency": "GBP", "action": "delivery", "manual_mode_capture": True, "notes": None, "restRef": "elas"}`.
  - `generate_payment_intent_url(order)` without URLs: the payload has no `success_url` key.
- **New `tests/utils_common/payment_ms/test_return_urls.py`:**
  - `web_return_urls`: with `config_values["WEB_STOREFRONT_URL"]="https://restaurant-test.ordelo.app/"` it returns `https://restaurant-test.ordelo.app/checkout/return?order=ELAS-ABCD-1` and `.../checkout?resume=1` (trailing slash trimmed). With the key unset it returns `None`.
  - `wa_return_urls`: `"elas"`, `"SFCS"` and `"bnat"` map to their links, with success equal to cancel. `"crms"` and `""` return `None`.
- **`tests/watomation/routers/test_order_hooks.py`:**
  - Fakes at L125–131 and L283 currently take `(food_order)`. Change them to `(food_order, **kwargs)` and record `kwargs`.
  - Add an assertion that an ELAS delivery passes `return_urls == {"success_url": "https://wa.me/message/AIDICBLAE4KZH1", "cancel_url": same}`.
  - Add a case where an unknown rest_ref passes `return_urls=None`.
- **Web checkout:** there is no existing unit harness for `web_checkout.create()` (it needs the DB). If one can be built cheaply with the patterns in `tests/fixtures`, assert the generator receives `web_return_urls(...)`. Otherwise this is covered by manual test M5.

Run (after the runbook §1 shell prep): `pytest tests/utils_common/payment_ms tests/watomation/routers/test_order_hooks.py -q && pytest -q && ruff check .`

---

## 5. restaurant-frontend change

`components/ordelo/CheckoutFlow.tsx` L487–489: delete the block

```tsx
{!isFixturesMode() && <p className="rounded-xl bg-sky-50 p-3 text-sm text-gray-800">
  Stripe may open the restaurant’s WhatsApp page after you pay. Use your saved order link to track this web order; you don’t need to send a WhatsApp message.
</p>}
```
Keep `<SaveOrderLink …/>` (L486). If `isFixturesMode` is no longer used anywhere in the file, remove it from the imports. Run `npm run lint && npm run build`. **Deploy only after** the payment service and OrdeloAgent are live, with `WEB_STOREFRONT_URL` set.

---

## 6. Local verification loop

Ports, matching the owner's Cloudflare tunnel:

| Service | Local | Tunnel host |
|---|---|---|
| OrdeloAgent | `http://localhost:3100` | `rider-agent-test.ordelo.app` |
| restaurant-frontend | `http://localhost:3000` | `restaurant-test.ordelo.app` |
| payment-service (local runner) | `http://localhost:4041` | `vavi-agg-test.ordelo.app` |
| restaurant-agents (not in scope) | `http://localhost:3101` | `rest-agent-test.ordelo.app`, `elas-agg-test.ordelo.app` |

### 6.1 The one hard-code: point OrdeloAgent's test payment URL at the local runner

**File:** `OrdeloAgent/config/microservices_setting.py`. **Where:** directly after L42 `ms_settings = MicroServicesSettings(**agent_env)`.

```python
ms_settings = MicroServicesSettings(**agent_env)
# LOCAL TEST ONLY - DO NOT COMMIT. Sends test-payment orders to the local payment-service runner.
ms_settings.stripe_url_test = "http://localhost:4041"
```

Why here:
- Every caller reads `ms_settings.stripe_url_test` at call time: `FoodOrder.payment_uri`, `food_order_pymodel.py` L221. That one line therefore redirects both web checkout and the WhatsApp menu path.
- Live orders keep `ms_settings.stripe_url` (L223) and go to the deployed live service.
- Which orders are "test" is unchanged:
  - `FoodOrder.uses_test_payment` (L196): `payment_mode == "test"`, or delivery from an overwatch number.
  - `payment_mode` is set by `resolve_payment_mode` (`utils_common/payment_ms/payment_mode.py`): a restaurant in `ordelo_config.TEST_PAYMENT_REST_REFS`, or an overwatch recipient with `?isTest3100=true`.

`http://localhost:4041` works because OrdeloAgent and the runner are on the same Mac. `https://vavi-agg-test.ordelo.app` works too (via the tunnel), and the runner accepts the path with or without `/prod`.

Guard against committing it:
- Before every OrdeloAgent commit, run `git diff --cached config/microservices_setting.py` and confirm it's empty.
- Or keep the line in a stash: `git stash push config/microservices_setting.py -m local-payment-url`, then `git stash pop` when testing.

### 6.2 Run commands

**Terminal A: payment-service (local runner, :4041)**
```zsh
cd /Users/basavaraj/bloop/payment-service
git switch feature/support-dynamic-successUrl
go version            # needs >= 1.20
go mod download
go vet ./... && go test ./...
go run ./cmd/local    # logs: "payment-service local runner on http://localhost:4041 (embedded config, Stripe test keys only)"
```
`PORT=4042 go run ./cmd/local` uses another port if needed. The runner never calls Secrets Manager, so AWS variables in the shell don't matter.

**Terminal B: OrdeloAgent (:3100)**, following `docs/local-testing-runbook.md` §1–2:
```zsh
cd /Users/basavaraj/bloop/OrdeloAgent
git switch feature/dynamic-payment-return-urls
if [[ -d venv ]]; then source venv/bin/activate; elif [[ -d .venv ]]; then source .venv/bin/activate; else echo "No virtual env found"; fi
export PYTHONPATH="$PWD"
[[ -f ".env" ]] && envLoad
# apply the §6.1 hard-code (or: git stash pop)
uv run watomation/fapp_ordelo_agent.py        # or: uv run --active ... when using venv/
```

**Terminal C: restaurant-frontend (:3000)**, runbook §3:
```zsh
cd /Users/basavaraj/bloop/restaurant-frontend
git switch feature/dynamic-payment-return-urls
npm run dev
```

**Terminal D: tunnel**, runbook §4. Reuse the running tunnel if there is one:
```zsh
cloudflared tunnel --config "$HOME/.cloudflared/config.yml" ingress validate
cloudflared tunnel --config "$HOME/.cloudflared/config.yml" run
```

**Database (maintenance window):**
1. Runbook §5: switch `ORDELO_APP_URL` → `https://rider-agent-test.ordelo.app` and `RESTAURANT_MENU_APP_URL` → `https://restaurant-test.ordelo.app`.
2. Add the new key and check the test list:
   ```sql
   -- new key (keep it after testing; it is the production value too)
   INSERT INTO ordelo_config (config_key, config_value)
   VALUES ('WEB_STOREFRONT_URL', 'https://restaurant-test.ordelo.app')
   ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value;

   -- which restaurants are always Stripe test
   SELECT config_key, config_value FROM ordelo_config
   WHERE config_key IN ('WEB_STOREFRONT_URL', 'TEST_PAYMENT_REST_REFS', 'overwatch_list');
   ```
   If `ordelo_config.config_key` has no unique constraint, use `UPDATE … WHERE config_key='WEB_STOREFRONT_URL'` and an `INSERT` only if 0 rows were updated. Restart OrdeloAgent, or wait 60 s, after changing it.

**Before E2E, one Stripe check:**
- The local runner creates sessions with the `sk_test_` keys in `config.yaml`. Stripe sends the `checkout.session.completed` event to the webhook endpoint registered **on that test account**, not to the laptop.
- In the Stripe test dashboard for that account, open Developers → Webhooks and confirm an endpoint exists. For ELAS test that's `…hjgttc1wpj…/prod/webhook/elai`, per `ordelo-agg-plan-cc.md` L40.
- If it's missing, the redirect still works (it's what we're testing). The order page will stay on "Confirming payment" because nothing marks the order paid.
- Use **delivery** orders: the deployed test Lambda may predate `58158ca`, so web collection capture is known to fail (open item T11).

### 6.3 Manual tests

**Direct `curl` against the runner** (no OrdeloAgent). Body template:
```zsh
BODY='{"items":[{"product_name":"Test burger","price":5.0,"quantity":1,"modifications":[]}],
"currency":"GBP","action":"delivery","manual_mode_capture":true,"notes":"local test","restRef":"elas"}'
curl -s -X POST "http://localhost:4041/threads/T-LOCAL/orders/ELAS-TEST-1/payment-url" \
  -H 'Content-Type: application/json' -d "$BODY"
```
Each call creates a real **test-mode** Checkout Session. Read the runner's `CreatePaymentURL returnURLs:` log line.

| # | Change to BODY | Expect |
|---|---|---|
| C1 | none | 200 `{"url":"https://checkout.stripe.com/..."}`; log `source=default success="https://wa.me/message/AIDICBLAE4KZH1"` |
| C2 | add `"success_url":"https://restaurant-test.ordelo.app/checkout/return?order=ELAS-TEST-1","cancel_url":"https://restaurant-test.ordelo.app/checkout?resume=1"` | 200; `source=request` with both URLs. Opening the session URL, paying with 4242 4242 4242 4242 lands on `/checkout/return?order=ELAS-TEST-1` |
| C3 | only `success_url` (as C2) | 200; `source=partial`, cancel = ELAS wa.me |
| C4 | `"success_url":"https://evil.com/x"` | 400 `invalid return URL: success_url: host "evil.com" not allowed`; no session created |
| C5 | `"cancel_url":"http://restaurant-test.ordelo.app/x"` | 400 `cancel_url: scheme must be https` |
| C6 | path `/prod/threads/T-LOCAL/orders/ELAS-TEST-1/payment-url` | same as C1 (adapter strips the stage) |
| C7 | `"restRef":"bnat"` | 200; default success = BNAT's default from `config.yaml` (`wa.me/message/F7QYDTUOIVCNI1`) |

**End to end through the tunnel**, with a test restaurant in `TEST_PAYMENT_REST_REFS` or an overwatch number:

| # | Flow | Steps | Expect |
|---|---|---|---|
| M5 | Web delivery, success | `https://restaurant-test.ordelo.app/town/<town>/<rest>` → basket → checkout → Pay → card 4242… | OrdeloAgent log shows the POST to `localhost:4041`; runner log `source=request`. Stripe returns to `/checkout/return?order=…`, which shows "Confirming your payment…", then the order page (if the payment event is processed, see §6.2) |
| M6 | Web cancel | Same, but press "←" on the Stripe page | Lands on `/checkout?resume=1` with the checkout restored (`resumed` banner in `CheckoutFlow.tsx` L354) |
| M7 | WhatsApp menu-page delivery, ELAS | Overwatch number, menu link with `?isTest3100=true` (or ELAS in the test list) → pay | Runner log `source=request success="https://wa.me/message/AIDICBLAE4KZH1"`; Stripe returns to ELAS WhatsApp |
| M8 | WhatsApp menu-page takeaway, BNAT | Same for BNAT takeaway | Return to `wa.me/message/F7QYDTUOIVCNI1` (Q7 change) |
| M9 | Fallback | `DELETE FROM ordelo_config WHERE config_key='WEB_STOREFRONT_URL'`, restart OrdeloAgent, place a web order | Runner log `source=default`; Stripe returns to wa.me (old behaviour). Re-insert the key afterwards |
| M10 | Old payment service + new OrdeloAgent | Remove the §6.1 hard-code (test orders go to the deployed test Lambda), place a web order | Order is created and payment works; return still goes to wa.me (unknown fields ignored), so shipping OrdeloAgent first is safe |

Inspect an order's records with `.claude/skills/ordelo-local-automatic-orders/references/inspect-order.sql` (runbook §"Reusable order-testing skill").

### 6.4 Restore after testing

1. Remove the §6.1 line (`git checkout config/microservices_setting.py` or re-stash it).
2. Runbook §7: restore `ORDELO_APP_URL` and `RESTAURANT_MENU_APP_URL`.
3. Keep `WEB_STOREFRONT_URL` (it's the production value), unless web ordering moves to another host.
4. Stop the runner (Ctrl+C). Stop the tunnel only if you started it.
5. Optional: expire stray test Checkout Sessions in the Stripe test dashboard.

---

## 7. Release order

1. **OrdeloAgent:** safe to deploy first (M10). Make sure `WEB_STOREFRONT_URL` exists in production ordelo_config.
2. **payment-service:** deploy to **every** Lambda behind the live and test gateways (`ms_stripe_url` `z0hydw9v90…`, `ms_stripe_url_test` `0af50z1k40…`, and the webhook gateways). `buildspec.yml` only updates the Lambda named `payment` (see `ordelo-agg-plan-cc.md` L40). This branch is based on `main` @ `58158ca`, so it also ships the collection-capture fix.
3. **Production smoke test:** one web delivery at the test restaurant (lands on `/checkout/return`) and one WhatsApp order (lands on wa.me).
4. **restaurant-frontend:** deploy the note removal.
5. **Docs:**
   - `ordelo-agg-plan-cc.md`: mark D26/§13.1 resolved and change the `/checkout/return` row (L593) from "Deferred" to live.
   - Add an ADR in `OrdeloAgent/docs/adr/`: "Per-order Stripe return URLs".
   - Update `docs/payment_and_order_flow.md` if it describes the redirect.

Later (not in this change): make the fields required once every caller sends them, including restaurant-agents' chat payment links in `packages/restaurant-agent-runtime/src/restaurant_agent_runtime/services/payment_ms/payment.py`. Then drop the per-restaurant `successurl`/`cancelurl` from the payment-service config.

## 8. Done when

- [ ] `go vet ./... && go test ./...` passes (payment-service).
- [ ] `pytest -q && ruff check .` passes (OrdeloAgent); the existing exact-payload test is unchanged.
- [ ] `npm run lint && npm run build` passes (frontend).
- [ ] C1–C7 and M5–M10 pass locally.
- [ ] The §6.1 hard-code is not in any commit (`git log -p -- config/microservices_setting.py`).
- [ ] Commits are on the three branches, not pushed.
