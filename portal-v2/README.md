# Portal v2 (presentation only)

Vite + React client of the existing SparkBench `/api/*` control plane.
Does not add operator or install services. Legacy UI stays at `/`.

```bash
cd portal-v2
npm install
SPARK_HOST=sparky npm run dev    # http://localhost:5173/v2/
npm run build                    # → portal/v2/
```
