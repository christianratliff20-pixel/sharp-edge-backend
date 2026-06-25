"""
SHARP EDGE - COMPLETE BACKEND (UPDATED)
FastAPI + SQLAlchemy + PostgreSQL + Odds API Integration
Copy this ENTIRE file into your main.py - replaces everything
"""

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Boolean, JSON, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
import jwt
import os
import secrets
import hashlib
import base64
from io import BytesIO
from PIL import Image
import pytesseract
import re
import asyncio
import aiohttp
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# CONFIGURATION
# ==========================================

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/sharp_edge")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

# Odds API
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")  # Get from odds-api.com
ODDS_API_URL = "https://api.the-odds-api.com/v4"

# ==========================================
# DATABASE SETUP
# ==========================================

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# DATABASE MODELS
# ==========================================

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    
    subscription_tier = Column(String, default="free")
    subscription_plan = Column(String, nullable=True)
    
    trial_start_date = Column(DateTime, nullable=True)  # NULL = new user, needs demo/pricing
    trial_days = Column(Integer, default=14)
    
    selected_sports = Column(JSON, default=list)
    selected_bet_types = Column(JSON, default=list)
    risk_tolerance = Column(String, default="medium")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConnectedSportsbook(Base):
    __tablename__ = "connected_sportsbooks"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    sportsbook_name = Column(String)
    auth_token = Column(String, nullable=True)
    refresh_token = Column(String, nullable=True)
    oauth_provider = Column(String)
    
    last_sync = Column(DateTime, default=datetime.utcnow)
    sync_status = Column(String, default="active")
    sync_error_message = Column(String, nullable=True)
    
    account_email = Column(String)
    account_username = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SyncedBet(Base):
    __tablename__ = "synced_bets"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    sportsbook_id = Column(String, index=True)
    sportsbook_name = Column(String)
    
    sport = Column(String, index=True)
    matchup = Column(String)
    bet_type = Column(String)
    selection = Column(String)
    odds = Column(String)
    amount_wagered = Column(Float)
    
    game_start_time = Column(DateTime)
    sport_event_id = Column(String, nullable=True)
    
    result = Column(String, nullable=True)
    amount_won = Column(Float, nullable=True)
    settled_at = Column(DateTime, nullable=True)
    
    external_bet_id = Column(String, unique=True)
    sportsbook_response = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    synced_at = Column(DateTime, default=datetime.utcnow)


class BetScreenshot(Base):
    __tablename__ = "bet_screenshots"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    filename = Column(String)
    image_data = Column(LargeBinary)
    extracted_text = Column(String, nullable=True)
    status = Column(String, default="pending")
    parsed_bets = Column(JSON, nullable=True)
    upload_date = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class Game(Base):
    __tablename__ = "games"
    
    id = Column(String, primary_key=True, index=True)
    sport = Column(String, index=True)
    matchup = Column(String)
    home_team = Column(String)
    away_team = Column(String)
    kickoff_time = Column(DateTime, index=True)
    
    odds_data = Column(JSON)  # All odds from different sportsbooks
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ==========================================
# PYDANTIC MODELS
# ==========================================

class SignUpRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: str = None
    last_name: str = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserProfile(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    subscription_tier: str
    subscription_plan: str
    trial_days_left: int
    selected_sports: list
    selected_bet_types: list
    risk_tolerance: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    upcoming_games_today: int
    trial_days_left: int
    predicted_roi_today: float
    win_rate_percentage: float
    total_predictions: int


class ConnectedSportsbookResponse(BaseModel):
    sportsbook_name: str
    account_email: str
    last_sync: datetime
    sync_status: str
    sync_error_message: str = None

    class Config:
        from_attributes = True


class SyncedBetResponse(BaseModel):
    id: str
    sport: str
    matchup: str
    bet_type: str
    selection: str
    odds: str
    amount_wagered: float
    game_start_time: datetime
    result: str = None
    amount_won: float = None
    sportsbook_name: str
    created_at: datetime

    class Config:
        from_attributes = True


class SyncedBetsStatsResponse(BaseModel):
    total_bets: int
    total_wins: int
    total_losses: int
    total_pending: int
    total_wagered: float
    total_won: float
    roi_percentage: float
    win_rate_percentage: float


class BetScreenshotResponse(BaseModel):
    id: str
    filename: str
    status: str
    parsed_bets: list = None
    upload_date: datetime

    class Config:
        from_attributes = True


class GameResponse(BaseModel):
    id: str
    sport: str
    matchup: str
    home_team: str
    away_team: str
    kickoff_time: datetime
    odds_data: dict

    class Config:
        from_attributes = True


# ==========================================
# APP SETUP
# ==========================================

app = FastAPI(title="Sharp Edge", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"Database initialization warning: {e}")

# ==========================================
# UTILITY FUNCTIONS
# ==========================================

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hash_password(plain_password) == hashed_password


def create_access_token(user_id: str, expires_delta: timedelta = None):
    if expires_delta is None:
        expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    expire = datetime.utcnow() + expires_delta
    to_encode = {"sub": user_id, "exp": expire}
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(authorization: str = None, db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user


async def parse_bet_screenshot(image_data: bytes) -> str:
    try:
        image = Image.open(BytesIO(image_data))
        extracted_text = pytesseract.image_to_string(image)
        return extracted_text
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Screenshot parsing failed: {str(e)}")


def extract_bets_from_text(ocr_text: str, sportsbook: str) -> list:
    bets = []
    
    if sportsbook.lower() == "draftkings":
        pattern = r'([\w\s]+?)\s+([+-]?\d+\.?\d*)\s+\$(\d+(?:,\d{3})*(?:\.\d{2})?)\s+(Pending|Win|Loss|Push)'
        matches = re.findall(pattern, ocr_text, re.MULTILINE)
        
        for match in matches:
            team, line, amount, status = match
            bets.append({
                "selection": team.strip(),
                "line": line,
                "amount_wagered": float(amount.replace(",", "")),
                "result": status.lower(),
                "sportsbook": "DraftKings",
            })
    
    elif sportsbook.lower() == "fanduel":
        pattern = r'([\w\s]+?)\s+@\s+([+-]?\d+\.?\d*)\s+\$(\d+(?:,\d{3})*(?:\.\d{2})?)'
        matches = re.findall(pattern, ocr_text, re.MULTILINE)
        
        for match in matches:
            team, line, amount = match
            bets.append({
                "selection": team.strip(),
                "line": line,
                "amount_wagered": float(amount.replace(",", "")),
                "sportsbook": "FanDuel",
            })
    
    return bets


async def calculate_bet_stats(user_id: str, db: Session) -> SyncedBetsStatsResponse:
    bets = db.query(SyncedBet).filter(SyncedBet.user_id == user_id).all()
    
    total_bets = len(bets)
    total_wins = sum(1 for b in bets if b.result == "win")
    total_losses = sum(1 for b in bets if b.result == "loss")
    total_pending = sum(1 for b in bets if b.result == "pending" or b.result is None)
    
    total_wagered = sum(b.amount_wagered for b in bets)
    total_won = sum(b.amount_won for b in bets if b.amount_won)
    
    roi_percentage = ((total_won - total_wagered) / total_wagered * 100) if total_wagered > 0 else 0
    win_rate_percentage = (total_wins / (total_wins + total_losses) * 100) if (total_wins + total_losses) > 0 else 0
    
    return SyncedBetsStatsResponse(
        total_bets=total_bets,
        total_wins=total_wins,
        total_losses=total_losses,
        total_pending=total_pending,
        total_wagered=total_wagered,
        total_won=total_won,
        roi_percentage=round(roi_percentage, 2),
        win_rate_percentage=round(win_rate_percentage, 2),
    )


async def fetch_games_from_odds_api(sport: str = None) -> list:
    """
    Fetch upcoming games with odds from The Odds API
    Supports: NFL, NBA, MLB, NHL, MLS, NCAAFB, NCAAMB, etc.
    """
    
    if not ODDS_API_KEY:
        logger.warning("ODDS_API_KEY not set, returning mock data")
        return get_mock_games()
    
    try:
        sports_map = {
            "nfl": "americanfootball_nfl",
            "nba": "basketball_nba",
            "mlb": "baseball_mlb",
            "nhl": "icehockey_nhl",
            "mls": "soccer_usa_mls",
            "ncaafb": "americanfootball_ncaa",
            "ncaamb": "basketball_ncaa",
            "soccer": "soccer_epl",
        }
        
        api_sport = sports_map.get(sport.lower(), "americanfootball_nfl") if sport else "americanfootball_nfl"
        
        url = f"{ODDS_API_URL}/sports/{api_sport}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "spreads,moneyline",
            "oddsFormat": "american",
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            
            games_data = response.json()
            games = []
            
            for game in games_data.get("data", [])[:10]:  # Limit to 10 games
                games.append({
                    "id": game.get("id"),
                    "sport": sport or "NFL",
                    "matchup": f"{game['away_team']} @ {game['home_team']}",
                    "home_team": game.get("home_team"),
                    "away_team": game.get("away_team"),
                    "kickoff_time": game.get("commence_time"),
                    "odds_data": {
                        "bookmakers": game.get("bookmakers", [])
                    }
                })
            
            return games
    
    except Exception as e:
        logger.error(f"Error fetching from Odds API: {e}")
        return get_mock_games()


def get_mock_games() -> list:
    """Mock game data for testing (when API key not available)"""
    return [
        {
            "id": "game_1",
            "sport": "NFL",
            "matchup": "Kansas City @ San Francisco",
            "home_team": "San Francisco",
            "away_team": "Kansas City",
            "kickoff_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "odds_data": {
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "markets": [
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "San Francisco", "point": -3.5, "price": -110},
                                    {"name": "Kansas City", "point": 3.5, "price": -110}
                                ]
                            }
                        ]
                    }
                ]
            }
        },
        {
            "id": "game_2",
            "sport": "NBA",
            "matchup": "Los Angeles Lakers @ Boston Celtics",
            "home_team": "Boston Celtics",
            "away_team": "Los Angeles Lakers",
            "kickoff_time": (datetime.utcnow() + timedelta(days=2)).isoformat(),
            "odds_data": {
                "bookmakers": [
                    {
                        "key": "fanduel",
                        "title": "FanDuel",
                        "markets": [
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Boston Celtics", "point": -5.5, "price": -110},
                                    {"name": "Los Angeles Lakers", "point": 5.5, "price": -110}
                                ]
                            }
                        ]
                    }
                ]
            }
        }
    ]


# ==========================================
# AUTHENTICATION ENDPOINTS
# ==========================================

@app.post("/api/v1/auth/signup")
def signup(request: SignUpRequest, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_id = secrets.token_urlsafe(16)
    hashed_pw = hash_password(request.password)
    
    user = User(
        id=user_id,
        email=request.email,
        hashed_password=hashed_pw,
        first_name=request.first_name,
        last_name=request.last_name,
        trial_start_date=None,  # NULL until user completes demo/pricing
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    access_token = create_access_token(user.id)
    
    return {
        "user_id": user.id,
        "email": user.email,
        "access_token": access_token,
        "token_type": "bearer",
        "is_new_user": True
    }


@app.post("/api/v1/auth/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email).first()
    
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    access_token = create_access_token(user.id)
    
    # Check if user is new (no trial_start_date yet)
    is_new_user = user.trial_start_date is None
    
    return {
        "user_id": user.id,
        "email": user.email,
        "access_token": access_token,
        "token_type": "bearer",
        "is_new_user": is_new_user
    }


@app.post("/api/v1/auth/logout")
def logout(current_user: User = Depends(get_current_user)):
    return {"status": "logged out"}


@app.post("/api/v1/auth/complete-onboarding")
def complete_onboarding(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Called after user completes demo + pricing. Sets trial_start_date."""
    current_user.trial_start_date = datetime.utcnow()
    db.commit()
    return {"status": "onboarding complete", "trial_start_date": current_user.trial_start_date}


# ==========================================
# USER ENDPOINTS
# ==========================================

@app.get("/api/v1/users/profile")
def get_profile(current_user: User = Depends(get_current_user)):
    trial_days_left = 0
    if current_user.trial_start_date:
        trial_days_left = (current_user.trial_start_date + timedelta(days=current_user.trial_days) - datetime.utcnow()).days
        trial_days_left = max(0, trial_days_left)
    
    return UserProfile(
        id=current_user.id,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        subscription_tier=current_user.subscription_tier,
        subscription_plan=current_user.subscription_plan,
        trial_days_left=trial_days_left,
        selected_sports=current_user.selected_sports,
        selected_bet_types=current_user.selected_bet_types,
        risk_tolerance=current_user.risk_tolerance,
        created_at=current_user.created_at,
    )


# ==========================================
# GAMES & ODDS ENDPOINTS
# ==========================================

@app.get("/api/v1/games/upcoming", response_model=list)
async def get_upcoming_games(
    sport: str = Query(None, description="Filter by sport (NFL, NBA, MLB, NHL, etc.)"),
    current_user: User = Depends(get_current_user)
):
    """
    Get upcoming games with odds from all sportsbooks
    Returns live odds for spreads, moneyline, etc.
    """
    games = await fetch_games_from_odds_api(sport)
    return games


@app.get("/api/v1/games/nfl", response_model=list)
async def get_nfl_games(current_user: User = Depends(get_current_user)):
    """Get upcoming NFL games with odds"""
    return await fetch_games_from_odds_api("nfl")


@app.get("/api/v1/games/nba", response_model=list)
async def get_nba_games(current_user: User = Depends(get_current_user)):
    """Get upcoming NBA games with odds"""
    return await fetch_games_from_odds_api("nba")


@app.get("/api/v1/games/mlb", response_model=list)
async def get_mlb_games(current_user: User = Depends(get_current_user)):
    """Get upcoming MLB games with odds"""
    return await fetch_games_from_odds_api("mlb")


# ==========================================
# SPORTSBOOK ENDPOINTS
# ==========================================

@app.get("/api/v1/sportsbooks/available")
def get_available_sportsbooks():
    available = [
        {"name": "DraftKings", "id": "draftkings", "description": "Connect your DraftKings account"},
        {"name": "FanDuel", "id": "fanduel", "description": "Connect your FanDuel account"},
        {"name": "BetMGM", "id": "betmgm", "description": "Connect your BetMGM account"},
        {"name": "Caesars", "id": "caesars", "description": "Connect your Caesars Sportsbook account"},
        {"name": "Bettor", "id": "bettor", "description": "Connect your Bettor account"},
    ]
    return {"sportsbooks": available}


@app.get("/api/v1/sportsbooks/connected", response_model=list)
def get_connected_sportsbooks(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    connected = db.query(ConnectedSportsbook).filter(
        ConnectedSportsbook.user_id == current_user.id
    ).all()
    
    return [
        ConnectedSportsbookResponse(
            sportsbook_name=s.sportsbook_name,
            account_email=s.account_email,
            last_sync=s.last_sync,
            sync_status=s.sync_status,
            sync_error_message=s.sync_error_message,
        )
        for s in connected
    ]


@app.post("/api/v1/sportsbooks/connect-manual")
def connect_sportsbook_manual(
    sportsbook_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    existing = db.query(ConnectedSportsbook).filter(
        ConnectedSportsbook.user_id == current_user.id,
        ConnectedSportsbook.oauth_provider == sportsbook_id
    ).first()
    
    if existing:
        return {"status": "already_connected", "sportsbook": sportsbook_id}
    
    connection_id = secrets.token_urlsafe(16)
    connection = ConnectedSportsbook(
        id=connection_id,
        user_id=current_user.id,
        sportsbook_name=sportsbook_id.upper(),
        oauth_provider=sportsbook_id,
        sync_status="manual_mode",
    )
    db.add(connection)
    db.commit()
    
    return {
        "status": "connected",
        "sportsbook": sportsbook_id,
        "mode": "manual_upload",
    }


@app.post("/api/v1/sportsbooks/disconnect")
def disconnect_sportsbook(
    sportsbook_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    connection = db.query(ConnectedSportsbook).filter(
        ConnectedSportsbook.user_id == current_user.id,
        ConnectedSportsbook.oauth_provider == sportsbook_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="Sportsbook not connected")
    
    db.delete(connection)
    db.commit()
    
    return {"status": "disconnected", "sportsbook": sportsbook_id}


# ==========================================
# BET SCREENSHOT ENDPOINTS
# ==========================================

@app.post("/api/v1/bets/upload-screenshot")
async def upload_bet_screenshot(
    file: UploadFile = File(...),
    sportsbook: str = "DraftKings",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        contents = await file.read()
        ocr_text = await parse_bet_screenshot(contents)
        extracted_bets = extract_bets_from_text(ocr_text, sportsbook)
        
        screenshot_id = secrets.token_urlsafe(16)
        screenshot = BetScreenshot(
            id=screenshot_id,
            user_id=current_user.id,
            filename=file.filename,
            image_data=contents,
            extracted_text=ocr_text,
            status="parsed" if extracted_bets else "pending",
            parsed_bets=extracted_bets,
        )
        db.add(screenshot)
        db.commit()
        
        for idx, bet in enumerate(extracted_bets):
            synced_bet = SyncedBet(
                id=secrets.token_urlsafe(16),
                user_id=current_user.id,
                sportsbook_name=sportsbook,
                sport=bet.get("sport", "Unknown"),
                matchup=bet.get("matchup", "Unknown"),
                bet_type=bet.get("bet_type", "Unknown"),
                selection=bet.get("selection", ""),
                odds=bet.get("line", ""),
                amount_wagered=bet.get("amount_wagered", 0),
                game_start_time=datetime.utcnow(),
                result=bet.get("result", "pending"),
                external_bet_id=f"{screenshot_id}_{idx}",
                sportsbook_response=bet,
            )
            db.add(synced_bet)
        
        db.commit()
        
        return {
            "status": "success",
            "screenshot_id": screenshot_id,
            "extracted_bets_count": len(extracted_bets),
            "extracted_bets": extracted_bets,
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Upload failed: {str(e)}")


@app.get("/api/v1/bets/screenshots", response_model=list)
def get_user_screenshots(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    screenshots = db.query(BetScreenshot).filter(
        BetScreenshot.user_id == current_user.id
    ).order_by(BetScreenshot.upload_date.desc()).all()
    
    return [
        BetScreenshotResponse(
            id=s.id,
            filename=s.filename,
            status=s.status,
            parsed_bets=s.parsed_bets,
            upload_date=s.upload_date,
        )
        for s in screenshots
    ]


# ==========================================
# BET TRACKING ENDPOINTS
# ==========================================

@app.get("/api/v1/bets/today", response_model=list)
def get_today_bets(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    bets = db.query(SyncedBet).filter(
        SyncedBet.user_id == current_user.id,
        SyncedBet.game_start_time >= today_start,
        SyncedBet.game_start_time < today_end,
    ).order_by(SyncedBet.game_start_time).all()
    
    return [
        SyncedBetResponse(
            id=b.id,
            sport=b.sport,
            matchup=b.matchup,
            bet_type=b.bet_type,
            selection=b.selection,
            odds=b.odds,
            amount_wagered=b.amount_wagered,
            game_start_time=b.game_start_time,
            result=b.result,
            amount_won=b.amount_won,
            sportsbook_name=b.sportsbook_name,
            created_at=b.created_at,
        )
        for b in bets
    ]


@app.get("/api/v1/bets/stats")
async def get_bets_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stats = await calculate_bet_stats(current_user.id, db)
    return stats


@app.get("/api/v1/bets/history")
def get_bets_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    days: int = 30,
    limit: int = 100
):
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    bets = db.query(SyncedBet).filter(
        SyncedBet.user_id == current_user.id,
        SyncedBet.synced_at >= cutoff_date,
    ).order_by(SyncedBet.game_start_time.desc()).limit(limit).all()
    
    return [
        SyncedBetResponse(
            id=b.id,
            sport=b.sport,
            matchup=b.matchup,
            bet_type=b.bet_type,
            selection=b.selection,
            odds=b.odds,
            amount_wagered=b.amount_wagered,
            game_start_time=b.game_start_time,
            result=b.result,
            amount_won=b.amount_won,
            sportsbook_name=b.sportsbook_name,
            created_at=b.created_at,
        )
        for b in bets
    ]


# ==========================================
# DASHBOARD ENDPOINT
# ==========================================

@app.get("/api/v1/dashboard")
def get_dashboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    trial_days_left = 0
    if current_user.trial_start_date:
        trial_days_left = (current_user.trial_start_date + timedelta(days=current_user.trial_days) - datetime.utcnow()).days
        trial_days_left = max(0, trial_days_left)
    
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    today_bets = db.query(SyncedBet).filter(
        SyncedBet.user_id == current_user.id,
        SyncedBet.game_start_time >= today_start,
        SyncedBet.game_start_time < today_end,
    ).limit(3).all()
    
    all_bets = db.query(SyncedBet).filter(SyncedBet.user_id == current_user.id).all()
    total_bets = len(all_bets)
    wins = sum(1 for b in all_bets if b.result == "win")
    win_rate = (wins / total_bets * 100) if total_bets > 0 else 0
    
    stats = DashboardStats(
        upcoming_games_today=len(today_bets),
        trial_days_left=trial_days_left,
        predicted_roi_today=0.0,
        win_rate_percentage=win_rate,
        total_predictions=total_bets,
    )
    
    user_profile = UserProfile(
        id=current_user.id,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        subscription_tier=current_user.subscription_tier,
        subscription_plan=current_user.subscription_plan,
        trial_days_left=trial_days_left,
        selected_sports=current_user.selected_sports,
        selected_bet_types=current_user.selected_bet_types,
        risk_tolerance=current_user.risk_tolerance,
        created_at=current_user.created_at,
    )
    
    bet_responses = [
        SyncedBetResponse(
            id=b.id,
            sport=b.sport,
            matchup=b.matchup,
            bet_type=b.bet_type,
            selection=b.selection,
            odds=b.odds,
            amount_wagered=b.amount_wagered,
            game_start_time=b.game_start_time,
            result=b.result,
            amount_won=b.amount_won,
            sportsbook_name=b.sportsbook_name,
            created_at=b.created_at,
        )
        for b in today_bets
    ]
    
    return {
        "user": user_profile,
        "stats": stats,
        "today_bets": bet_responses,
    }


# ==========================================
# HEALTH CHECK
# ==========================================

@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
