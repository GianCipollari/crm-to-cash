"""Static word lists used to build realistic LatAm company and person names.

Kept in code (instead of a library like Faker) so the generator has no heavy
dependencies and the output is identical on every machine.
"""

FIRST_NAMES = [
    "Agustín", "Ana", "Bruno", "Camila", "Carlos", "Carolina", "Daniela", "Emilia",
    "Facundo", "Florencia", "Gabriel", "Guadalupe", "Ignacio", "Isabella", "Javier",
    "Julieta", "Lautaro", "Laura", "Lucas", "Luciana", "Manuel", "María", "Mateo",
    "Micaela", "Nicolás", "Paula", "Pedro", "Renata", "Rodrigo", "Romina", "Santiago",
    "Sara", "Sebastián", "Silvina", "Thiago", "Victoria", "Joaquín", "Pilar", "Andrés",
    "Natalia",
]

LAST_NAMES = [
    "Acosta", "Aguirre", "Álvarez", "Benítez", "Cabrera", "Díaz", "Domínguez",
    "Fernández", "Flores", "García", "Giménez", "Gómez", "González", "Gutiérrez",
    "Herrera", "López", "Martínez", "Medina", "Molina", "Morales", "Navarro", "Núñez",
    "Ortiz", "Pereyra", "Pérez", "Ramírez", "Ríos", "Rodríguez", "Romero", "Ruiz",
    "Sánchez", "Sosa", "Suárez", "Torres", "Vargas", "Vega", "Silva", "Rojas", "Castro",
    "Luna",
]

COMPANY_PREFIXES = [
    "Andes", "Austral", "Pampa", "Litoral", "Patagonia", "Delta", "Cumbre", "Horizonte",
    "Sur", "Norte", "Río", "Altos", "Brisa", "Cóndor", "Puerto", "Valle", "Sierra",
    "Atlántico", "Pacífico", "Nexo", "Vértice", "Aurora", "Faro", "Quebracho", "Ceibo",
]

COMPANY_CORES = [
    "Logística", "Alimentos", "Construcciones", "Distribuidora", "Agro", "Textil",
    "Servicios", "Tecnología", "Metalúrgica", "Farma", "Transportes", "Consultores",
    "Energía", "Inmobiliaria", "Comercial", "Industrias", "Seguros", "Laboratorios",
]

LEGAL_FORMS = ["S.A.", "S.R.L.", "S.A.S.", "S.A. de C.V.", "Ltda."]

INDUSTRIES = [
    "Retail", "Manufacturing", "Logistics", "Agriculture", "Construction",
    "Professional Services", "Healthcare", "Technology", "Food & Beverage", "Energy",
]

COUNTRIES = {  # country code -> weight
    "AR": 0.40, "MX": 0.20, "CL": 0.15, "CO": 0.15, "UY": 0.10,
}

PRODUCTS = [
    "Contable Cloud - Plan Pyme (annual)",
    "Contable Cloud - Plan Empresa (annual)",
    "Contable Cloud - Implementation services",
    "Contable Cloud - Payroll add-on (annual)",
]
