"""School results from the Ontario open school file. No third-party licence."""

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from mls.services.ontario_schools import SOURCE, schools_near, top_gta_schools


class SchoolsNearAPIView(APIView):
    """GET /api/mls/schools/near/?lat=&lon=&radius=8"""

    permission_classes = [AllowAny]

    def get(self, request):
        try:
            lat = float(request.query_params.get("lat", ""))
            lon = float(request.query_params.get("lon", ""))
        except ValueError:
            return Response({"error": "lat and lon are required numbers."}, status=400)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return Response({"error": "lat and lon are out of range."}, status=400)
        try:
            radius = float(request.query_params.get("radius") or 8)
        except ValueError:
            return Response({"error": "radius must be a number."}, status=400)
        radius = min(20.0, max(1.0, radius))
        return Response({
            **SOURCE,
            "schools": schools_near(lat, lon, radius_km=radius),
        })


class TopSchoolsAPIView(APIView):
    """GET /api/mls/schools/top/?limit=4"""

    permission_classes = [AllowAny]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 4)
        except ValueError:
            return Response({"error": "limit must be a number."}, status=400)
        limit = min(8, max(1, limit))
        return Response({
            **SOURCE,
            "schools": top_gta_schools(limit=limit),
        })
