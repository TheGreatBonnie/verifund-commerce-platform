FROM node:24-alpine

WORKDIR /app
COPY apps/console/package.json apps/console/package-lock.json ./
RUN npm ci
COPY apps/console . .
RUN npm run build

CMD ["npm", "start"]
