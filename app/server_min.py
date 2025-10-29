from fastapi import FastAPI
print('>>> LOADED (min):', __file__)
app = FastAPI(title='Smoke Test')
@app.get('/')
def root():
    return {'ok': True, 'msg': 'root ok'}
@app.get('/routes')
def routes():
    return [r.path for r in app.router.routes]
