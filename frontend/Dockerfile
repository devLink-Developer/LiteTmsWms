FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json* /app/
RUN npm install

COPY . /app

EXPOSE 8021

CMD ["npm", "run", "dev"]
