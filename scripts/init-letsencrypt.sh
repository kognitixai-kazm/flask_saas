#!/bin/bash
# ============================================
# init-letsencrypt.sh — إصدار الشهادة الأولى من Let's Encrypt
# مقتبس من: https://github.com/wmnnd/nginx-certbot
# ============================================

if ! [ -x "$(command -v docker-compose)" ] && ! [ -x "$(command -v docker)" ]; then
  echo 'خطأ: لم يتم العثور على docker أو docker compose.' >&2
  exit 1
fi

# ============================================
# الإعدادات
# ============================================
domains=(YOUR_DOMAIN www.YOUR_DOMAIN)
rsa_key_size=4096
data_path="./data/certbot"
email="YOUR_EMAIL@gmail.com" # أضف إيميلك هنا للإشعارات
staging=0 # غيّر إلى 1 لتجربة الإصدار بدون تجاوز حدود Let's Encrypt

if [ -d "$data_path" ]; then
  read -p "يوجد بيانات سابقة للشهادات. هل تريد استبدالها؟ (y/N) " decision
  if [ "$decision" != "Y" ] && [ "$decision" != "y" ]; then
    exit
  fi
fi

echo "### تحميل إعدادات TLS موصى بها ..."
mkdir -p "$data_path/conf"
curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf > "$data_path/conf/options-ssl-nginx.conf"
curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem > "$data_path/conf/ssl-dhparams.pem"
echo

echo "### إنشاء شهادة وهمية (Dummy Certificate) لبدء Nginx ..."
path="/etc/letsencrypt/live/$domains"
mkdir -p "$data_path/conf/live/$domains"
docker compose -f docker-compose.production.yml run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:$rsa_key_size -days 1\
    -keyout '$path/privkey.pem' \
    -out '$path/fullchain.pem' \
    -subj '/CN=localhost'" certbot
echo


echo "### تشغيل Nginx ..."
docker compose -f docker-compose.production.yml up --force-recreate -d nginx
echo

echo "### حذف الشهادة الوهمية ..."
docker compose -f docker-compose.production.yml run --rm --entrypoint "\
  rm -Rf /etc/letsencrypt/live/$domains && \
  rm -Rf /etc/letsencrypt/archive/$domains && \
  rm -Rf /etc/letsencrypt/renewal/$domains.conf" certbot
echo


echo "### طلب شهادة Let's Encrypt الحقيقية ..."
# الانضمام للمتغيرات للـ command
domain_args=""
for domain in "${domains[@]}"; do
  domain_args="$domain_args -d $domain"
done

# تحديد الإيميل أو الوضع التجريبي
case "$email" in
  "") email_arg="--register-unsafely-without-email" ;;
  *) email_arg="--email $email" ;;
esac

if [ $staging != "0" ]; then staging_arg="--staging"; fi

docker compose -f docker-compose.production.yml run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $staging_arg \
    $email_arg \
    $domain_args \
    --rsa-key-size $rsa_key_size \
    --agree-tos \
    --force-renewal" certbot
echo

echo "### إعادة تشغيل Nginx لتحميل الشهادة الجديدة ..."
docker compose -f docker-compose.production.yml exec nginx nginx -s reload
