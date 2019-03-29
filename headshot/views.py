import mimetypes
import json
import time
import os
import sys
import json
from werkzeug.utils import secure_filename
from django.shortcuts import render
from django.http import Http404
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from django.http import Http404
from rest_framework import permissions, status
from rest_framework.exceptions import ParseError
from rest_framework.parsers import FileUploadParser, MultiPartParser, FormParser
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_yasg.utils import swagger_auto_schema
import cloudinary
import cloudinary.uploader
import cloudinary.api
import stripe
from headshot.models import Headshot
from headshot.serializers import HeadshotSerializer
from headshot.create_serializers import HeadshotCreateSerializer
from headshot.detail_serializers import HeadshotDetailSerializer
from headshot.upload_serializers import HeadshotUploadSerializer
from headshot.payment_serializers import HeadshotPaymentSerializer
from stripe_payment.models import StripePayment

stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.log = 'info'  # or 'debug'


class HeadshotList(APIView):
    """
    Retrieve all headshot.
    """
    @swagger_auto_schema(responses={200: HeadshotSerializer(many=True)})
    def get(self, request, format=None):
        headshots = Headshot.objects.all()
        serializer = HeadshotSerializer(headshots, many=True)
        return Response(serializer.data)


class HeadshotDetail(APIView):
    """
    Retrieve, update or delete a headshot.
    """
    def get_object(self, pk):
        try:
            return Headshot.objects.get(pk=pk)
        except Headshot.DoesNotExist:
            raise Http404

    @swagger_auto_schema(responses={200: HeadshotDetailSerializer(many=False)})
    def get(self, request, pk, format=None):
        headshot = self.get_object(pk)
        serializer = HeadshotDetailSerializer(headshot)
        return Response(serializer.data)

    @swagger_auto_schema(
        request_body=HeadshotCreateSerializer,
        responses={200: HeadshotSerializer(many=False)}
    )
    def put(self, request, pk, format=None):
        headshot = self.get_object(pk)
        serializer = HeadshotSerializer(headshot, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(responses={200: 'OK'})
    def delete(self, request, pk, format=None):
        headshot = self.get_object(pk)
        headshot.delete()
        return Response({'id': int(pk)}, status=status.HTTP_200_OK)


class HeadshotCreate(APIView):
    """
    Get a new headshot
    """

    @swagger_auto_schema(request_body=HeadshotCreateSerializer,
                         responses={200: HeadshotSerializer(many=False)})
    def post(self, request, format=None):
        serializer = HeadshotCreateSerializer(data=request.data)

        if serializer.is_valid():
            new_headshot = Headshot(**serializer.validated_data)
            new_headshot.save()
            new_serializer = HeadshotSerializer(new_headshot, many=False)
            return Response(new_serializer.data, status=status.HTTP_201_CREATED)

        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

class HeadshotUpload(APIView):
    """
    Get a new headshot with uploaded image
    """
    parser_class = ( MultiPartParser, FormParser)
    # height = 500
    # width = 400
    # page_id = 1

    @swagger_auto_schema(request_body=HeadshotUploadSerializer,
                         responses={200: HeadshotDetailSerializer(many=False)})
    def put(self, request, pk, format=None):
        headshot = Headshot.objects.get(pk=pk)

        # serializer = HeadshotUploadSerializer(data=request.data)

        # if serializer.is_valid():
        if 'file' not in request.data:
            print("Empty content")
            return Response({'error': 'Empty content'}, status=status.HTTP_400_BAD_REQUEST)

        if not headshot:
            return Response({'error': 'Not found the headshot'}, status=status.HTTP_400_BAD_REQUEST)

        # Save temp file
        f = request.data['file']
        # file_name = request.data['fileName']
        # Upload image from frontend to cloudinary
        cloudinary.config( 
            cloud_name = "dnxe2ejbx", 
            api_key = "531987746948979", 
            api_secret = "mAG_-w5YQXBqUrvd5umM42QCyvI" 
        )

        res = cloudinary.uploader.upload(f)

        headshot.public_id = res['public_id']
        headshot.signature = res['signature']
        headshot.image_format = res['format']
        headshot.width = res['width']
        headshot.height = res['height']
        headshot.cloudinary_image_url = res['url']
        headshot.cloudinary_image_secure_url = res['secure_url']
        headshot.status = 'Required'
        headshot.save()
        new_serializer = HeadshotSerializer(headshot)

        return Response(new_serializer.data, status=status.HTTP_200_OK)


class HeadshotPayment(APIView):
    """
    Create payment for a headshot
    """

    def checkout(self, token, amount, headshot):
        try:
            charge = stripe.Charge.create(
                amount=amount,
                currency='USD',
                source=token['id'],
                description='{user} charge to print {file_name} on {image_url}'.format(
                    user=headshot.email,
                    file_name=headshot.file_name,
                    image_url=headshot.cloudinary_image_secure_url
                ),
                statement_descriptor='headshot_id: {headshot_id}.'.format(
                    headshot_id=headshot.id
                ),
                # metadata={'order_id': 12345}
            )

            # Only confirm an order after you have status: succeeded
            print("______STATUS_____", charge['status'])  # should be succeeded
            if charge['status'] == 'succeeded':
                return Response({'message': 'Your transaction has been successful.'})
            else:
                raise stripe.error.CardError
        except stripe.error.CardError as e:
            body = e.json_body
            err = body.get('error', {})
            print('Status is: %s' % e.http_status)
            print('Type is: %s' % err.get('type'))
            print('Code is: %s' % err.get('code'))
            print('Message is %s' % err.get('message'))
            return Response(
                {"message": err.get('message')},
                status=e.http_status
            )
        except stripe.error.RateLimitError as e:
            # Too many requests made to the API too quickly
            return Response(
                {'message': "The API was not able to respond, try again."}, 
                status=status.HTTP_403_FORBIDDEN
            )
        except stripe.error.InvalidRequestError as e:
            # invalid parameters were supplied to Stripe's API
            return Response(
                {'message': "Invalid parameters, unable to process payment."}, 
                status=status.HTTP_403_FORBIDDEN
            )
        except stripe.error.AuthenticationError as e:
            # Authentication with Stripe's API failed
            # (maybe you changed API keys recently)
            pass
        except stripe.error.APIConnectionError as e:
            # Network communication with Stripe failed
            return Response(
                {'message': 'Network communication failed, try again.'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        except stripe.error.StripeError as e:
            # Display a very generic error to the user, and maybe
            # send yourself an email
            return Response(
                {'message': 'Internal Error, contact support.'}, 
                status=status.HTTP_403_FORBIDDEN
            )

        # Something else happened, completely unrelated to Stripe
        except Exception as e:
            return Response(
                {'message': 'Unable to process payment, try again.'}, 
                status=status.HTTP_403_FORBIDDEN
            )

    def create_customer(self, headshot, stripe_payment, amount):
        customer = stripe.Customer.create(
            email='paying.user@example.com',
            source=stripe_payment.source,
        )
        print('==== customer: ', customer)
        stripe_payment.customer_id = customer.id
        stripe_payment.save()


    @swagger_auto_schema(request_body=HeadshotPaymentSerializer,
                         responses={200: HeadshotDetailSerializer(many=False)})
    def post(self, request, pk, format=None):
        headshot = Headshot.objects.get(pk=pk)
        # if serializer.is_valid():
        if 'token' not in request.data:
            return Response({'error': 'Empty token'}, status=status.HTTP_400_BAD_REQUEST)

        if 'amount' not in request.data:
            return Response({'error': 'Empty amount'}, status=status.HTTP_400_BAD_REQUEST)

        if not headshot:
            return Response({'error': 'Not found the headshot'}, status=status.HTTP_400_BAD_REQUEST)

        token = request.data['token']
        amount = request.data['amount']
        card = token['card']

        new_stripe_payment = StripePayment.objects.create(headshot_id=headshot.id)
        new_stripe_payment.token_id = token['id']
        new_stripe_payment.source = token['id']
        new_stripe_payment.card_id = card['id']
        new_stripe_payment.address_city = card['address_city'] if card['address_city'] else ''
        new_stripe_payment.address_country = card['address_country'] if card['address_country'] else ''
        new_stripe_payment.address_line1 = card['address_line1'] if card['address_line1'] else ''
        new_stripe_payment.address_line1_check = card['address_line1_check'] if card['address_line1_check'] else ''
        new_stripe_payment.address_line2 = card['address_line2'] if card['address_line2'] else ''
        new_stripe_payment.address_state = card['address_state'] if card['address_state'] else ''
        new_stripe_payment.address_zip = card['address_zip'] if card['address_zip'] else ''
        new_stripe_payment.address_zip_check = card['address_zip_check'] if card['address_zip_check'] else ''
        new_stripe_payment.brand = card['brand'] if card['brand'] else ''
        new_stripe_payment.exp_month = card['exp_month']
        new_stripe_payment.exp_year = card['exp_year']
        new_stripe_payment.last4 = card['last4'] if card['last4'] else ''
        new_stripe_payment.livemode = token['livemode']
        new_stripe_payment.amount = amount
        new_stripe_payment.save()
        
        headshot.status="Required"
        headshot.save()



        # Create stripe payment
        return self.checkout(token, amount, headshot)
        