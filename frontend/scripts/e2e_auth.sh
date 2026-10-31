set -u
B=http://localhost:3000
J=/tmp/jar.txt; rm -f $J
EMAIL="auth-$(date +%s)@example.com"
ok(){ if [ "$2" = "$3" ]; then echo "PASS $1 ($2)"; else echo "FAIL $1: got $2 expected $3"; FAILED=1; fi; }
FAILED=0
code(){ curl -s -o /dev/null -w '%{http_code}' "$@"; }

ok "unauth /dashboard -> redirect"          "$(code $B/dashboard)" 307
ok "redirect target keeps next"             "$(curl -s -o /dev/null -w '%{redirect_url}' $B/dashboard)" "$B/login?next=%2Fdashboard"
ok "unauth / -> redirect"                   "$(code $B/)" 307
ok "GET /login public"                      "$(code $B/login)" 200
ok "GET /register public"                   "$(code $B/register)" 200
ok "GET /forgot-password public"            "$(code $B/forgot-password)" 200
ok "GET /reset-password public"             "$(code $B/reset-password)" 200
ok "proxy: unauth /auth/me -> 401"          "$(code $B/api/v1/auth/me)" 401
echo "     401 body: $(curl -s $B/api/v1/auth/me)"
ok "register (validation) short pw -> 422"  "$(code -X POST $B/api/v1/auth/register -H 'content-type: application/json' -d '{"email":"x@example.com","password":"short"}')" 422
ok "register via proxy -> 201"              "$(code -c $J -X POST $B/api/v1/auth/register -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"correct-horse-9\",\"full_name\":\"Ada Lovelace\"}")" 201
echo "     cookie flags: $(grep access_token $J | awk '{print ($1 ~ /#HttpOnly_/ ? "HttpOnly" : "NOT-HttpOnly"), "path="$3}')"
ok "dup register -> 409"                    "$(code -X POST $B/api/v1/auth/register -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"correct-horse-9\"}")" 409
ok "me with cookie -> 200"                  "$(code -b $J $B/api/v1/auth/me)" 200
echo "     me: $(curl -s -b $J $B/api/v1/auth/me)"
ok "authed /dashboard -> 200"               "$(code -b $J $B/dashboard)" 200
ok "authed /login -> redirect"              "$(code -b $J $B/login)" 307
ok "authed /login redirects to /dashboard"  "$(curl -s -o /dev/null -w '%{redirect_url}' -b $J $B/login)" "$B/dashboard"
ok "bad password -> 401"                    "$(code -X POST $B/api/v1/auth/login -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"wrong-password\"}")" 401
echo "     login-fail body: $(curl -s -X POST $B/api/v1/auth/login -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"wrong-password\"}")"
ok "logout -> 200"                          "$(code -b $J -c $J -X POST $B/api/v1/auth/logout)" 200
ok "me after logout -> 401"                 "$(code -b $J $B/api/v1/auth/me)" 401
ok "dashboard after logout -> redirect"     "$(code -b $J $B/dashboard)" 307
ok "login again -> 200"                     "$(code -c $J -X POST $B/api/v1/auth/login -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"correct-horse-9\"}")" 200
ok "forgot-password (unknown email) -> 200" "$(code -X POST $B/api/v1/auth/forgot-password -H 'content-type: application/json' -d '{"email":"nobody@example.com"}')" 200
ok "reset-password bad token -> 4xx"       "$( [ "$(code -X POST $B/api/v1/auth/reset-password -H 'content-type: application/json' -d '{"token":"bogus","new_password":"another-pass-1"}')" -ge 400 ] && echo 4xx )" 4xx
echo; [ $FAILED = 0 ] && echo "ALL PASSED" || echo "SOME FAILED"
