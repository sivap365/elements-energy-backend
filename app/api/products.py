from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.models import Product
from app.schemas.schemas import ProductCreate, ProductResponse

router = APIRouter(prefix="/products", tags=["Products"])


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    """
    Create a new product with an initial stock count.
    SKU must be unique across all products.
    """
    product = Product(
        sku=payload.sku,
        name=payload.name,
        stock=payload.stock,
    )
    db.add(product)
    try:
        db.commit()
        db.refresh(product)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A product with SKU '{payload.sku}' already exists.",
        )
    return product


@router.get(
    "/{sku}",
    response_model=ProductResponse,
    summary="Get a product by SKU",
)
def get_product(sku: str, db: Session = Depends(get_db)):
    """
    Fetch a product's details and current stock by its SKU.
    """
    product = db.execute(
        select(Product).where(Product.sku == sku)
    ).scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with SKU '{sku}' not found.",
        )
    return product
