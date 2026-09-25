FROM node:22-alpine AS build

WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM node:22-alpine
ENV PORT=8080
WORKDIR /app
RUN npm install --global serve@14
COPY --from=build /app/dist ./dist
CMD ["sh", "-c", "serve -s dist -l ${PORT}"]
