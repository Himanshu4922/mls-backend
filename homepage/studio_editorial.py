"""Staff CRUD for homepage lists that already live in Django admin."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from vlog.permissions import IsStaffUser

from .models import BuyerIncentive, CommunityImage, NewsArticle, Partner
from .serializers import (
    BuyerIncentiveSerializer,
    CommunityImageSerializer,
    NewsArticleSerializer,
    PartnerSerializer,
)


class _Staff(APIView):
    permission_classes = [IsStaffUser]


class StudioIncentiveListView(_Staff):
    def get(self, request):
        rows = BuyerIncentive.objects.all()
        return Response({"results": BuyerIncentiveSerializer(rows, many=True).data})

    def post(self, request):
        serializer = BuyerIncentiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class StudioIncentiveDetailView(_Staff):
    def patch(self, request, pk: int):
        row = get_object_or_404(BuyerIncentive, pk=pk)
        serializer = BuyerIncentiveSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk: int):
        get_object_or_404(BuyerIncentive, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudioPartnerListView(_Staff):
    def get(self, request):
        return Response({"results": PartnerSerializer(Partner.objects.all(), many=True).data})

    def post(self, request):
        serializer = PartnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class StudioPartnerDetailView(_Staff):
    def patch(self, request, pk: int):
        row = get_object_or_404(Partner, pk=pk)
        serializer = PartnerSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk: int):
        get_object_or_404(Partner, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudioCommunityImageListView(_Staff):
    def get(self, request):
        return Response({"results": CommunityImageSerializer(CommunityImage.objects.all(), many=True).data})

    def post(self, request):
        serializer = CommunityImageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class StudioCommunityImageDetailView(_Staff):
    def patch(self, request, city_key: str):
        key = city_key.strip().lower()
        row = CommunityImage.objects.filter(city_key=key).first()
        payload = {**dict(request.data), "city_key": key}
        if row is None:
            # First save for a city that only had a frontend fallback photo.
            serializer = CommunityImageSerializer(data=payload)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        serializer = CommunityImageSerializer(row, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, city_key: str):
        get_object_or_404(CommunityImage, city_key=city_key.strip().lower()).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudioNewsListView(_Staff):
    def get(self, request):
        rows = NewsArticle.objects.select_related("source")[:50]
        return Response({"results": NewsArticleSerializer(rows, many=True).data})


class StudioNewsDetailView(_Staff):
    def patch(self, request, pk: int):
        row = get_object_or_404(NewsArticle, pk=pk)
        hidden = request.data.get("is_hidden")
        if not isinstance(hidden, bool):
            return Response({"detail": "Set is_hidden to true or false."}, status=status.HTTP_400_BAD_REQUEST)
        row.is_hidden = hidden
        row.save(update_fields=["is_hidden"])
        return Response(NewsArticleSerializer(row).data)
