# Hawanama - Pakistan Air Quality Monitoring

Real-time air quality monitoring platform for Pakistan, providing comprehensive data visualization, quality control, and public health insights.

## Live Demo
- **Frontend**: [hawanama-2.web.app](https://hawanama-2.web.app)
- **API**: [hawanama-152782825429.asia-south1.run.app](https://hawanama-152782825429.asia-south1.run.app)

## Architecture

Production deployment on Google Cloud Platform with cloud-native architecture:

### Frontend
- **Next.js 15** with TypeScript and App Router
- **Mapbox GL JS** with clustering for interactive maps
- **TailwindCSS** for styling
- **Firebase Hosting** with SSR functions

### Backend
- **FastAPI** with Pydantic for type-safe APIs
- **TimescaleDB Cloud** for time-series and spatial data
- **Google Cloud Run** for serverless API hosting
- **Google Cloud Scheduler** for automated data ingestion

### Infrastructure
- **Google Cloud Platform** (hawanama-2 project)
- **Firebase Hosting** for frontend delivery
- **Cloud Run** for scalable API deployment
- **Cloud Scheduler** for cron jobs

## Features

- **Real-time monitoring** from IQAir API
- **Interactive maps** with station clustering and real-time data
- **City and station pages** with detailed AQI information
- **Time-series charts** showing air quality trends
- **Health advisory** with AQI face indicators
- **RESTful API** for data access
- **Responsive design** for mobile and desktop

## Development Setup

### Prerequisites
- Node.js 18+ (for frontend development)
- Python 3.11+ (for backend development)
- Google Cloud SDK (for deployment)
- Firebase CLI (for frontend deployment)

### Frontend Development

1. **Clone and setup**:
   ```bash
   git clone https://github.com/PakAirQuality/hawanama
   cd hawanama/apps/web-next
   npm install
   ```

2. **Start development server**:
   ```bash
   npm run dev
   ```

### Backend Development

1. **Setup backend**:
   ```bash
   cd hawanama/apps/api
   pip install -r requirements.txt
   ```

2. **Start local API**:
   ```bash
   uvicorn main:app --reload --port 8001
   ```

### Local Services
- **Frontend**: http://localhost:3000
- **Local API**: http://localhost:8001

## Project Structure

```
hawanama/
├── apps/
│   ├── api/              # FastAPI backend
│   ├── web-next/         # Next.js frontend
│   └── worker/           # Data ingestion workers
├── infra/
│   ├── scheduler.tf      # Terraform for Cloud Scheduler
│   └── terraform files   # GCP infrastructure
├── firebase.json         # Firebase hosting config
├── cloudbuild.yaml       # Cloud Build configuration
└── CLAUDE.md             # Technical documentation
```

## Deployment

### Frontend Deployment
```bash
cd apps/web-next
npm run build
firebase deploy --only hosting,functions
```

### Backend Deployment
```bash
cd apps/api
gcloud run deploy hawanama --source . --region asia-south1
```

### Infrastructure
```bash
cd infra
terraform plan
terraform apply
```

## Data Sources

- **IQAir**: Real-time air quality data from monitoring stations
- **TimescaleDB Cloud**: External database for time-series storage
- **Station coverage**: Major cities across Pakistan

## Monitoring & Operations

- **Cloud Scheduler**: Automated hourly data collection
- **Cloud Run**: Auto-scaling API with zero downtime
- **Firebase Hosting**: CDN-backed frontend delivery
- **Health checks**: Automatic station discovery and validation

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/new-feature`
3. Make your changes and test thoroughly
4. Commit: `git commit -m 'Add new feature'`
5. Push: `git push origin feature/new-feature`
6. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- **IQAir** for providing air quality data
- **TimescaleDB** for time-series database optimization
- **Google Cloud Platform** for hosting infrastructure
- **Firebase** for frontend hosting and deployment

## Contact

- **Project Lead**: [PakAirQuality](https://github.com/PakAirQuality)
- **Issues**: [GitHub Issues](https://github.com/PakAirQuality/hawanama/issues)
- **Discussions**: [GitHub Discussions](https://github.com/PakAirQuality/hawanama/discussions)