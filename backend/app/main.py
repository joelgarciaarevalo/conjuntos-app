from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
import app.models
from app.routers import auth, conjuntos, inmuebles, zonas_comunes, reservas, pqrs

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sistema de Conjuntos Residenciales")

# CORS debe ir primero, antes de los routers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(conjuntos.router)
app.include_router(inmuebles.router)
app.include_router(zonas_comunes.router)
app.include_router(reservas.router)
app.include_router(pqrs.router)

@app.get("/")
def root():
    return {"mensaje": "API funcionando "}