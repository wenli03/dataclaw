package main

import (
	"encoding/json"
	"net/http"
	"time"
)

func jsonDecodeReader(r *http.Request, v any) error {
	defer r.Body.Close()
	return json.NewDecoder(http.MaxBytesReader(nil, r.Body, 1<<20)).Decode(v)
}

func nowTime() time.Time { return time.Now() }
